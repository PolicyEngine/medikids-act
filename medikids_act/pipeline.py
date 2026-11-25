"""Run the estimate in stages, one process per stage.

    python -m medikids_act.pipeline lookback
    python -m medikids_act.pipeline baseline
    python -m medikids_act.pipeline case floor      (and each other case)
    python -m medikids_act.pipeline checks
    python -m medikids_act.pipeline tables

Each simulation stage runs one national PolicyEngine US microsimulation on the
certified dataset and writes person-level and tax-unit-level arrays to the
results folder. ``checks`` and ``tables`` only read those files.

The results folder is ``$MEDIKIDS_RESULTS`` if set, otherwise ``results/`` in
the repository (ignored by git). Result tables are not committed.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import threading
import time
from importlib import metadata
from pathlib import Path

import numpy as np

from medikids_act import assumptions as A
from medikids_act import cases as C
from medikids_act import coverage as COV

ROOT = Path(__file__).resolve().parents[1]
Y = A.YEAR

# The certified dataset is a 2024 file; the engine ages it to later years.
DATA_YEAR = 2024

PERSON_BOOL = (
    *COV.ENGINE_INPUTS,
    COV.INDIAN_HEALTH_SERVICE,
    "is_medicaid_eligible",
    "medikids_existing_group_eligible",
    "medikids_federal_immigration_eligible",
    "is_medicaid_ineligible_due_to_work_requirement",
    "is_chip_eligible",
    "is_basic_health_program_eligible",
    "pays_aca_premium",
    # Inputs, read back so the checks can confirm they reached the run.
    "medikids_lookback_eligible",
    "medikids_lookback_adult_group",
    "medikids_in_aca_adult_group",
)
PERSON_FLOAT = (
    "age",
    "medicaid_cost",
    "medicaid_federal_cost",
    "medicaid_state_cost",
    "medicaid_federal_share",
    "medicaid_cost_if_enrolled",
    "medikids_group_rate",
    "medikids_group_rate_cost",
    "medikids_group_rate_federal_cost",
    "chip",
    "chip_federal_cost",
    "chip_state_cost",
    "medicaid_slcsp_state_denominator",
)
PERSON_ENUM = ("state_code_str", "medicaid_category", "chip_category", "immigration_status")
TAX_UNIT_FLOAT = ("assigned_aca_ptc", "aca_ptc", "basic_health_program")


def results_dir() -> Path:
    path = Path(os.environ.get("MEDIKIDS_RESULTS", ROOT / "results"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def log(message: str) -> None:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9  # bytes on macOS
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"{stamp} {message} (peak rss {peak:.1f} GB)", flush=True)


def code_version() -> str:
    """The repository commit the run used, with a mark if the tree had uncommitted changes."""
    import subprocess

    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else ""

    commit = git("rev-parse", "HEAD") or "unknown"
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    return commit + ("+uncommitted" if dirty else "")


def provenance(dataset: str | None, code_at_start: str) -> dict:
    """What a stage ran on: package versions, the dataset file and its hash, the code commit.

    ``dataset`` is ``None`` for the certified bundle, or the path of a
    development sample, which is labeled as such and never reported.
    ``code_at_start`` is ``code_version()`` taken when the stage function began,
    before it imported the reform; if the tree has moved by the time the stage
    finishes, the recorded version says so and the provenance check fails.
    """
    from policyengine.provenance import dataset_materialization as dm

    manifest_path = Path(
        metadata.distribution("policyengine").locate_file("policyengine/data/bundle/manifest.json")
    )
    us = json.loads(manifest_path.read_text())["data_releases"]["us"]
    if dataset is None:
        path = require_local_dataset()
        name, build, certified = us["default_dataset"], us["build_id"], True
    else:
        path = Path(dataset)
        name, build, certified = path.name, "development sample (not reportable)", False
    return {
        "versions": {
            p: metadata.version(p) for p in ("policyengine", "policyengine-us", "policyengine-core")
        },
        "dataset": name,
        "data_build": build,
        "dataset_certified": certified,
        "dataset_file": str(Path(path).resolve()),
        "dataset_sha256": dm.sha256_file(Path(path)),
        "year": Y,
        "code_version": code_at_start
        if code_version() == code_at_start
        else code_at_start + "+changed-during-stage",
    }


def require_local_dataset() -> Path:
    """Stop unless the certified dataset is already on disk with the right hash.

    ``policyengine`` downloads the file (about 0.8 GB) into ``./data`` when it
    is missing. A run should never start a download that size by surprise, so
    this refuses unless ``MEDIKIDS_ALLOW_DOWNLOAD=1``.
    """
    from policyengine.provenance import dataset_materialization as dm

    spec = dm._resolve_bundle_dataset("us")
    present = spec.destination.is_file() and dm.sha256_file(spec.destination) == spec.sha256
    if not present and os.environ.get("MEDIKIDS_ALLOW_DOWNLOAD") != "1":
        raise SystemExit(
            f"The certified dataset is not at {spec.destination.resolve()} (or its hash "
            "differs). Running would download about 0.8 GB. Put the file there, or set "
            "MEDIKIDS_ALLOW_DOWNLOAD=1 to let policyengine fetch it."
        )
    return spec.destination


def guard_memory() -> None:
    """End the process if its peak memory passes ``MEDIKIDS_MAX_RSS_GB``.

    A shared machine may enforce its own ceiling on heavy runs. Stopping here
    first, with a clear message, keeps this run from tripping it.
    """
    limit = float(os.environ.get("MEDIKIDS_MAX_RSS_GB", "0"))
    if limit <= 0:
        return

    def watch() -> None:
        while True:
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9
            if peak > limit:
                print(
                    f"peak memory {peak:.1f} GB passed the {limit:.1f} GB limit; stopping",
                    flush=True,
                )
                os._exit(86)
            time.sleep(1)

    threading.Thread(target=watch, daemon=True).start()


def make_simulation(reform, dataset: str | None = None):
    """A country-package microsimulation on the certified bundle, with ``reform``.

    ``dataset`` names another file (a development sample). Results from such a
    run are not on the certified data and are never reported.
    """
    import policyengine as pe

    if dataset is None:
        require_local_dataset()
        return pe.us.managed_microsimulation(reform=reform)
    return pe.us.managed_microsimulation(dataset=dataset, allow_unmanaged=True, reform=reform)


def _array(sim, name: str, period=Y, entity: str | None = "person") -> np.ndarray:
    """One value per member of ``entity`` (``None`` keeps the variable's own entity)."""
    values = sim.calculate(name, period, map_to=entity) if entity else sim.calculate(name, period)
    if hasattr(values, "decode_to_str"):
        values = values.decode_to_str()
    values = np.asarray(values)
    # Text is stored as fixed-width strings so the files load without pickle.
    return values.astype(str) if values.dtype == object else values


def _sum_by_state(values: np.ndarray, state: np.ndarray) -> dict[str, float]:
    return {s: float(values[state == s].sum()) for s in np.unique(state)}


def run_lookback(out: Path, dataset: str | None) -> None:
    """Eligibility under the rules in effect on 2025-01-01, and the price base."""
    started = code_version()
    from medikids_act.reform import SKIPPED_AT_LOOKBACK, lookback_inputs, lookback_reform

    sim = make_simulation(lookback_reform(), dataset)
    log("lookback simulation built")
    state = _array(sim, "state_code_str")
    age = _array(sim, "age")
    eligible = _array(sim, "medikids_lookback_title_xix_eligible").astype(bool)
    category = _array(sim, "medicaid_category")
    aca_adult = _array(sim, "medikids_in_aca_adult_group").astype(bool)
    enrolled = _array(sim, "medicaid_enrolled").astype(bool)
    flags = lookback_inputs(eligible, aca_adult, _array(sim, "medicaid_income_level"))
    index = _array(sim, "medicaid_slcsp_cost_index_filled").astype(float)
    base_weight = _array(sim, "person_weight", DATA_YEAR).astype(float)
    # Per-enrollee prices rest on each state's spending total divided by the
    # index-weighted enrollment the model produces at the dataset's own weights
    # under the rules in force when the totals were measured.
    by_state = _sum_by_state(base_weight * index * enrolled, state)
    denominator = np.array([by_state[s] for s in state])
    model_person_weight = _array(sim, "person_weight").astype(float)
    model_under_26 = float(model_person_weight[age < A.AGE_LIMIT].sum())
    weight_scale = A.under_26_population_target() / model_under_26
    np.savez_compressed(
        out / "lookback.npz",
        state_code_str=state,
        age=age.astype(np.float32),
        lookback_eligible=flags["medikids_lookback_eligible"],
        lookback_adult_group=flags["medikids_lookback_adult_group"],
        lookback_category=category,
        lookback_in_aca_adult_group=aca_adult,
        lookback_separate_chip=_array(sim, "is_chip_eligible").astype(bool),
        lookback_enrolled=enrolled,
        cost_index=index.astype(np.float32),
        base_person_weight=base_weight,
        denominator=denominator,
        household_weight_model=_array(sim, "household_weight", entity=None).astype(float),
        weight_scale=np.float64(weight_scale),
    )
    meta = provenance(dataset, started) | {
        "stage": "lookback",
        "parameters_without_a_lookback_value": sorted(set(SKIPPED_AT_LOOKBACK)),
        "model_under_26_before_rescaling": model_under_26,
        "under_26_target": A.under_26_population_target(),
        "weight_scale": weight_scale,
        "states_with_zero_denominator": sorted(s for s, v in by_state.items() if v <= 0),
    }
    (out / "lookback.json").write_text(json.dumps(meta, indent=1))
    log("lookback written")


def _apply_shared_inputs(sim, look) -> None:
    """Inputs every scenario shares. Set before anything is calculated."""
    sim.set_input(
        "household_weight", Y, look["household_weight_model"] * float(look["weight_scale"])
    )
    sim.set_input("medicaid_slcsp_state_denominator", Y, look["denominator"])
    sim.set_input("medikids_lookback_eligible", Y, look["lookback_eligible"])
    sim.set_input("medikids_lookback_adult_group", Y, look["lookback_adult_group"])


def _collect(sim, extra_person_float=()) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for name in PERSON_BOOL:
        arrays[name] = _array(sim, name).astype(bool)
    for name in (*PERSON_FLOAT, *extra_person_float):
        arrays[name] = _array(sim, name).astype(np.float64)
    for name in PERSON_ENUM:
        arrays[name] = _array(sim, name)
    for name in TAX_UNIT_FLOAT:
        arrays[f"tax_unit__{name}"] = _array(sim, name, entity="tax_unit").astype(np.float64)
    # In family-tier rating states the engine's cost index is a share of a
    # family premium, so a person's index moves when relatives enroll.
    arrays["family_tier"] = _array(sim, "slcsp_family_tier_applies", f"{Y}-01").astype(bool)
    arrays["person_weight"] = _array(sim, "person_weight").astype(np.float64)
    arrays["tax_unit_weight"] = _array(sim, "tax_unit_weight", entity=None).astype(np.float64)
    arrays["person_household_id"] = _array(sim, "person_household_id")
    arrays["person_id"] = _array(sim, "person_id")
    arrays["person_tax_unit_id"] = _array(sim, "person_tax_unit_id")
    arrays["tax_unit_id"] = _array(sim, "tax_unit_id", entity=None)
    return arrays


def read_survey_columns(dataset: str | None, person_id: np.ndarray) -> dict[str, np.ndarray]:
    """Survey coverage items from the dataset's person table, in simulation order.

    The engine has no variables for these columns, so they are read from the
    same file the simulation runs on and matched on person id.
    """
    import pandas as pd

    path = dataset or str(require_local_dataset())
    with pd.HDFStore(path, mode="r") as store:
        table = store.select("person", columns=["person_id", *COV.SURVEY_COLUMNS])
    table = table.set_index("person_id")
    if not table.index.is_unique or not np.isin(person_id, table.index).all():
        raise ValueError("the simulation's people do not match the dataset's person table")
    table = table.loc[person_id]
    return {name: table[name].to_numpy() for name in COV.SURVEY_COLUMNS}


def run_baseline(out: Path, dataset: str | None) -> None:
    """Current law in the reporting year, with this analysis's cost conventions."""
    started = code_version()
    from medikids_act.reform import current_law_reform

    look = np.load(out / "lookback.npz")
    sim = make_simulation(current_law_reform(), dataset)
    _apply_shared_inputs(sim, look)
    log("baseline simulation built")
    arrays = _collect(sim)
    arrays.update(COV.survey_inputs(read_survey_columns(dataset, arrays["person_id"])))
    coverage, record = COV.classify(
        arrays,
        age=arrays["age"],
        weights=arrays["person_weight"],
        household_id=arrays["person_household_id"],
    )
    arrays["coverage"] = coverage
    arrays["coverage_measured"] = record["measured"]
    arrays["coverage_imputed"] = record["imputed"]
    np.savez_compressed(out / "baseline.npz", **arrays)
    meta = provenance(dataset, started) | {
        "stage": "baseline",
        "uninsured_rate_by_cell": record["uninsured_rate_by_cell"],
    }
    (out / "baseline.json").write_text(json.dumps(meta, indent=1))
    log("baseline written")


def run_case(case: str, out: Path, dataset: str | None) -> None:
    """The bill under one switching case."""
    started = code_version()
    from medikids_act.reform import READINGS, medikids_reform

    look = np.load(out / "lookback.npz")
    base = np.load(out / "baseline.npz")
    enrolls = C.case_enrolls(
        case,
        age=base["age"],
        coverage=base["coverage"],
        household_id=base["person_household_id"],
    )
    sim = make_simulation(medikids_reform(), dataset)
    _apply_shared_inputs(sim, look)
    sim.set_input("medikids_case_enrolls", Y, enrolls)
    log(f"case {case} simulation built")
    alternative = [
        f"medikids_{cost}_federal_cost_{reading}"
        for reading in READINGS[1:]
        for cost in ("medicaid", "group_rate")
    ]
    arrays = _collect(sim, extra_person_float=alternative)
    arrays["case_enrolls"] = enrolls
    np.savez_compressed(out / f"case_{case}.npz", **arrays)
    meta = provenance(dataset, started) | {
        "stage": f"case_{case}",
        "description": C.DESCRIPTIONS[case],
    }
    (out / f"case_{case}.json").write_text(json.dumps(meta, indent=1))
    log(f"case {case} written")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=("lookback", "baseline", "case", "checks", "tables"))
    parser.add_argument("case", nargs="?", choices=C.CASES)
    parser.add_argument("--dataset", help="development sample file (results are not reportable)")
    parser.add_argument("--out", help="results folder (default: $MEDIKIDS_RESULTS or results/)")
    args = parser.parse_args()
    out = Path(args.out) if args.out else results_dir()
    out.mkdir(parents=True, exist_ok=True)
    guard_memory()
    started = time.time()
    if args.stage == "lookback":
        run_lookback(out, args.dataset)
    elif args.stage == "baseline":
        run_baseline(out, args.dataset)
    elif args.stage == "case":
        if args.case is None:
            parser.error("the case stage needs a case name")
        run_case(args.case, out, args.dataset)
    elif args.stage == "checks":
        from medikids_act.checks import run_checks

        raise SystemExit(run_checks(out))
    else:
        from medikids_act.tables import write_tables

        write_tables(out)
    log(f"{args.stage} done in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
