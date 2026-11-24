"""Invariants the run outputs must satisfy before any number is reported.

    python -m medikids_act.pipeline checks

Each check reads the arrays the simulation stages wrote, prints PASS or FAIL
with the evidence, and the command exits non-zero if any check fails. The
checks print counts of violations and tolerances, never result totals.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
from microdf import MicroSeries

from medikids_act import assumptions as A
from medikids_act import cases as C
from medikids_act.coverage import Coverage
from medikids_act.reform import READINGS

DOLLAR_TOLERANCE = 0.01  # per person or per tax unit
RELATIVE_TOLERANCE = 1e-6
FLOAT32_RELATIVE = 1e-6


def load(out: Path, stage: str) -> dict[str, np.ndarray]:
    with np.load(out / f"{stage}.npz", allow_pickle=False) as data:
        return {name: data[name] for name in data.files}


def weighted_sum(values, weights, mask=None) -> float:
    values = np.asarray(values, dtype=float)
    if mask is not None:
        values = values * np.asarray(mask)
    return float(MicroSeries(values, weights=np.asarray(weights, dtype=float)).sum())


class Report:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.rows.append({"check": name, "passed": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}", flush=True)

    @property
    def failed(self) -> int:
        return sum(not row["passed"] for row in self.rows)


def _max_abs(a, b, mask=None) -> float:
    diff = np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float))
    if mask is not None:
        diff = diff[np.asarray(mask)]
    return float(diff.max()) if diff.size else 0.0


def _inputs_reached(report: Report, name: str, run: dict, look: dict) -> None:
    """The lookback outputs and the price base must arrive in every run unchanged."""
    same = (
        np.array_equal(run["medikids_lookback_eligible"], look["lookback_eligible"])
        and np.array_equal(run["medikids_lookback_adult_group"], look["lookback_adult_group"])
        and np.allclose(
            run["medicaid_slcsp_state_denominator"], look["denominator"], rtol=1e-5, atol=0
        )
    )
    report.add(f"{name}: the lookback flags and the price base reached the run", same, "")


def check_inputs(report: Report, look: dict, base: dict) -> None:
    under_26 = base["age"] < A.AGE_LIMIT
    population = weighted_sum(under_26, base["person_weight"])
    target = A.under_26_population_target()
    report.add(
        "population under 26 equals the Census-based target",
        abs(population / target - 1) < RELATIVE_TOLERANCE,
        f"relative gap {population / target - 1:+.2e}",
    )
    report.add(
        "every state has a positive price base",
        bool((look["denominator"] > 0).all()),
        f"{int((look['denominator'] <= 0).sum())} people in states with no enrollment base",
    )
    report.add(
        "the lookback run finds people inside and outside the 2025 plan, and an adult group",
        bool(
            look["lookback_eligible"][under_26].any()
            and (~look["lookback_eligible"][under_26]).any()
            and look["lookback_adult_group"].any()
            and not (look["lookback_adult_group"] & ~look["lookback_eligible"]).any()
        ),
        "",
    )
    valid = np.isin(base["coverage"], [int(c) for c in Coverage])
    by_class = sum(
        weighted_sum((base["coverage"] == int(c)) & under_26, base["person_weight"])
        for c in Coverage
    )
    report.add(
        "every person has one coverage class and the classes sum to the population under 26",
        bool(valid.all()) and abs(by_class / population - 1) < 1e-9,
        f"{int((~valid).sum())} people without a valid class; class counts sum to the total "
        f"within {abs(by_class / population - 1):.1e}",
    )
    populated = [c.name for c in Coverage if not ((base["coverage"] == int(c)) & under_26).any()]
    report.add(
        "every coverage class has someone under 26 in it",
        not populated,
        f"empty classes: {populated}" if populated else "",
    )
    _inputs_reached(report, "baseline", base, look)


def check_accounting(report: Report, name: str, run: dict) -> None:
    # The engine defines federal cost as cost times share and state cost as the
    # rest, so this identity guards against a replaced variable breaking that
    # link. The group-rate pricing has no separate state variable: the tables
    # take state as total minus federal.
    parts = run["medicaid_federal_cost"] + run["medicaid_state_cost"]
    allowed = FLOAT32_RELATIVE * np.abs(run["medicaid_cost"]) + DOLLAR_TOLERANCE
    excess = np.abs(parts - run["medicaid_cost"]) - allowed
    report.add(
        f"{name}: federal plus state equals total Medicaid cost for every person",
        bool((excess <= 0).all()),
        f"{int((excess > 0).sum())} people outside single-precision rounding",
    )
    share = run["medicaid_federal_share"]
    report.add(
        f"{name}: federal share lies between 0 and 1",
        bool(((share >= 0) & (share <= 1)).all()),
        f"{int(((share < 0) | (share > 1)).sum())} people outside the range",
    )
    for cost, federal in (
        ("medicaid_cost", "medicaid_federal_cost"),
        ("medikids_group_rate_cost", "medikids_group_rate_federal_cost"),
    ):
        expected = run[cost] * share
        gap = np.abs(run[federal] - expected) - (
            FLOAT32_RELATIVE * np.abs(expected) + DOLLAR_TOLERANCE
        )
        report.add(
            f"{name}: {federal} equals {cost} times the federal share",
            bool((gap <= 0).all()),
            f"{int((gap > 0).sum())} people outside single-precision rounding",
        )
    enrolled = run["medicaid_enrolled"]
    off = float(np.abs(run["medicaid_cost"][~enrolled]).max()) if (~enrolled).any() else 0.0
    report.add(
        f"{name}: people who are not enrolled carry no Medicaid cost",
        off <= DOLLAR_TOLERANCE,
        f"largest amount ${off:.4f}",
    )


def _unit_has_change(run: dict, base: dict) -> np.ndarray:
    """For each person: did anyone in their tax unit change Medicaid enrollment?"""
    _, unit = np.unique(base["person_tax_unit_id"], return_inverse=True)
    changed = run["medicaid_enrolled"] != base["medicaid_enrolled"]
    return np.bincount(unit, weights=changed.astype(float))[unit] > 0


def check_case(report: Report, case: str, run: dict, base: dict, look: dict) -> None:
    under_26 = base["age"] < A.AGE_LIMIT
    older = ~under_26
    enrolled = run["medicaid_enrolled"]
    base_enrolled = base["medicaid_enrolled"]
    inside_plan = look["lookback_eligible"]
    _inputs_reached(report, case, run, look)

    expected = C.case_enrolls(
        case, age=base["age"], coverage=base["coverage"], household_id=base["person_household_id"]
    )
    report.add(
        f"{case}: the run used the case's enrollment set",
        np.array_equal(run["case_enrolls"], expected),
        f"{int((run['case_enrolls'] != expected).sum())} people differ",
    )
    moved = np.isin(base["coverage"], [int(Coverage.CHIP), int(Coverage.BASIC_HEALTH)]) & under_26
    report.add(
        f"{case}: no separate-CHIP or Basic Health Program enrollee under 26 is left uncovered",
        bool(moved.any()) and bool(enrolled[moved].all()),
        f"{int((~enrolled[moved]).sum())} of {int(moved.sum())} not enrolled in Medicaid",
    )
    report.add(
        f"{case}: everyone the case names is enrolled",
        bool(enrolled[expected].all()),
        f"{int((~enrolled[expected]).sum())} named but not enrolled",
    )
    regained = base["is_medicaid_ineligible_due_to_work_requirement"] & under_26
    unexplained = enrolled & ~base_enrolled & ~expected & ~regained
    report.add(
        f"{case}: every new enrollee is named by the case or regains Medicaid through the "
        "community engagement exception",
        not unexplained.any(),
        f"{int(unexplained.sum())} new enrollees unexplained",
    )
    report.add(
        f"{case}: nobody enrolled at baseline loses Medicaid, and nobody 26 or over gains it",
        bool(enrolled[base_enrolled].all()) and not (enrolled & ~base_enrolled & older).any(),
        f"{int((~enrolled[base_enrolled]).sum())} lost enrollment; "
        f"{int((enrolled & ~base_enrolled & older).sum())} gained it at 26 or over",
    )
    # A person's price depends on nobody else, except in family-tier states,
    # where it is a share of a family premium.
    both = enrolled & base_enrolled
    steady = both & (~base["family_tier"] | ~_unit_has_change(run, base))
    gap = _max_abs(run["medicaid_cost"], base["medicaid_cost"], steady)
    scale = max(float(np.abs(base["medicaid_cost"][steady]).max()) if steady.any() else 1.0, 1.0)
    report.add(
        f"{case}: people enrolled in both runs cost the same, unless a relative's enrollment "
        "changed in a family-tier state",
        bool(steady.any()) and gap <= RELATIVE_TOLERANCE * scale + DOLLAR_TOLERANCE,
        f"largest gap ${gap:.4f} among {int(steady.sum())} people",
    )
    gap = _max_abs(run["medikids_group_rate_cost"], base["medikids_group_rate_cost"], both)
    report.add(
        f"{case}: group-rate cost is the same for people enrolled in both runs",
        gap <= DOLLAR_TOLERANCE,
        f"largest gap ${gap:.4f}",
    )
    chip_young = float(np.abs(run["chip"][under_26]).max()) if under_26.any() else 0.0
    report.add(
        f"{case}: no separate-CHIP spending remains for anyone under 26",
        chip_young <= DOLLAR_TOLERANCE,
        f"largest remaining amount ${chip_young:.4f}",
    )
    gap = _max_abs(run["chip"], base["chip"], older)
    report.add(
        f"{case}: CHIP spending at 26 and over is unchanged",
        gap <= DOLLAR_TOLERANCE,
        f"largest gap ${gap:.4f}",
    )
    share, base_share = run["medicaid_federal_share"], base["medicaid_federal_share"]
    gap = _max_abs(share, base_share, both & older)
    report.add(
        f"{case}: the federal share of enrollees 26 and over is unchanged",
        gap <= 1e-6,
        f"largest gap {gap:.2e}",
    )
    # The bill does not move anyone between existing groups: a person who is
    # matched at baseline and inside the 2025 plan keeps their rate.
    keeps = both & under_26 & inside_plan & (base_share > 0)
    gap = _max_abs(share, base_share, keeps)
    report.add(
        f"{case}: enrollees under 26 with a matched group at baseline, inside the 2025 plan, "
        "keep their federal share",
        bool(keeps.any()) and gap <= 1e-6,
        f"largest gap {gap:.2e} among {int(keeps.sum())} people",
    )
    outside = enrolled & under_26 & ~inside_plan
    full = enrolled & (share >= 1 - 1e-6)
    report.add(
        f"{case}: the 100 percent match goes to every enrollee under 26 outside the 2025 plan, "
        "and to nobody else",
        bool(outside.any()) and np.array_equal(full, outside),
        f"{int((full & ~outside).sum())} draw 100 percent without qualifying; "
        f"{int((outside & ~full).sum())} qualify without drawing it",
    )
    primary = run["medicaid_federal_cost"]
    tolerance = FLOAT32_RELATIVE * np.abs(run["medicaid_cost"]) + DOLLAR_TOLERANCE
    ordered = (
        (run["medikids_medicaid_federal_cost_strict_v5"] <= primary + tolerance)
        & (run["medikids_medicaid_federal_cost_adult_group_100"] >= primary - tolerance)
        & (run["medikids_medicaid_federal_cost_adult_group_regular"] <= primary + tolerance)
    )
    differs = any(
        _max_abs(run[f"medikids_medicaid_federal_cost_{reading}"], primary) > DOLLAR_TOLERANCE
        for reading in READINGS[1:]
    )
    report.add(
        f"{case}: the alternative readings bracket the primary one as their definitions imply, "
        "and at least one differs from it",
        bool(ordered.all()) and differs,
        f"{int((~ordered).sum())} people out of order",
    )
    if case == "everyone":
        report.add(
            "everyone: every person under 26 is enrolled",
            bool(enrolled[under_26].all()),
            f"{int((~enrolled[under_26]).sum())} not enrolled",
        )


def check_no_marketplace_switch(report: Report, case: str, run: dict, base: dict) -> None:
    """Where no Marketplace enrollee switches, the credit must not move at all."""
    credits = base["tax_unit__assigned_aca_ptc"]
    gap = _max_abs(run["tax_unit__assigned_aca_ptc"], credits)
    report.add(
        f"{case}: premium tax credits equal the baseline for every tax unit",
        bool((credits > 0).any()) and gap <= DOLLAR_TOLERANCE,
        f"largest gap ${gap:.4f} across {int((credits > 0).sum())} tax units with a credit",
    )
    changed = int((run["person_receives_aca"] != base["person_receives_aca"]).sum())
    report.add(
        f"{case}: subsidized Marketplace enrollment equals the baseline for every person",
        changed == 0,
        f"{changed} people changed",
    )


def check_floor(report: Report, floor: dict, base: dict) -> None:
    changed = int((floor["pays_aca_premium"] != base["pays_aca_premium"]).sum())
    report.add(
        "floor: Marketplace eligibility equals the baseline for every person",
        changed == 0,
        f"{changed} people changed",
    )
    weights = base["person_weight"]
    new = floor["medicaid_enrolled"] & ~base["medicaid_enrolled"]
    # Reconcile spending wherever one person's enrollment cannot reprice another.
    plain = ~base["family_tier"]
    change = weighted_sum(floor["medicaid_cost"], weights, plain) - weighted_sum(
        base["medicaid_cost"], weights, plain
    )
    added = weighted_sum(floor["medicaid_cost"], weights, new & plain)
    scale = max(abs(added), 1.0)
    report.add(
        "floor: Medicaid spending is the baseline plus the new enrollees (outside "
        "family-tier states)",
        bool((new & plain).any()) and abs(change - added) <= 1e-6 * scale,
        f"relative gap {abs(change - added) / scale:.2e}",
    )
    change = weighted_sum(floor["medikids_group_rate_cost"], weights) - weighted_sum(
        base["medikids_group_rate_cost"], weights
    )
    added = weighted_sum(floor["medikids_group_rate_cost"], weights, new)
    scale = max(abs(added), 1.0)
    report.add(
        "floor: group-rate Medicaid spending is the baseline plus the new enrollees",
        abs(change - added) <= 1e-9 * scale,
        f"relative gap {abs(change - added) / scale:.2e}",
    )


def check_nesting(report: Report, runs: dict[str, dict], base: dict) -> None:
    weights = base["person_weight"]
    unit_weights = base["tax_unit_weight"]
    orders = [
        C.CHAIN,
        ("floor", "newborns", "everyone"),
        ("uninsured", "uninsured_wide", "everyone"),
    ]
    seen = set()
    for order in orders:
        present = [c for c in order if c in runs]
        for earlier, later in itertools.pairwise(present):
            if (earlier, later) in seen:
                continue
            seen.add((earlier, later))
            a, b = runs[earlier], runs[later]
            added = b["medicaid_enrolled"] & ~a["medicaid_enrolled"]
            named = b["case_enrolls"] & ~a["medicaid_enrolled"]
            dropped = a["medicaid_enrolled"] & ~b["medicaid_enrolled"]
            report.add(
                f"{earlier} -> {later}: enrollment is nested and grows by exactly the people "
                "the larger case adds",
                not dropped.any() and bool(named.any()) and np.array_equal(added, named),
                f"{int(dropped.sum())} people only in the smaller case; "
                f"{int((added != named).sum())} differ from the named set; "
                f"{'grows' if named.any() else 'adds nobody'}",
            )
            for label, key in (
                ("Medicaid cost at group rates", "medikids_group_rate_cost"),
                ("federal Medicaid cost at group rates", "medikids_group_rate_federal_cost"),
                ("Medicaid cost at the engine's pricing", "medicaid_cost"),
                ("federal Medicaid cost at the engine's pricing", "medicaid_federal_cost"),
            ):
                lo, hi = weighted_sum(a[key], weights), weighted_sum(b[key], weights)
                report.add(
                    f"{earlier} -> {later}: {label} rises",
                    hi > lo,
                    "rises"
                    if hi > lo
                    else f"does not rise (relative change {(hi - lo) / lo:+.2e})",
                )
            lo = weighted_sum(a["tax_unit__assigned_aca_ptc"], unit_weights)
            hi = weighted_sum(b["tax_unit__assigned_aca_ptc"], unit_weights)
            report.add(
                f"{earlier} -> {later}: premium tax credits do not rise",
                hi <= lo + 1e-9 * max(abs(lo), 1.0),
                "fall or hold" if hi <= lo else f"rise by a relative {(hi - lo) / lo:.2e}",
            )


def check_provenance(report: Report, out: Path) -> None:
    """Every stage must come from the same committed code, so no stale file is mixed in."""
    versions = {}
    for path in sorted(out.glob("*.json")):
        if path.name == "checks.json":
            continue
        versions[path.stem] = json.loads(path.read_text()).get("code_version", "missing")
    distinct = sorted(set(versions.values()))
    clean = all("+uncommitted" not in v and v not in ("missing", "unknown") for v in distinct)
    report.add(
        "every stage ran on the same committed code",
        len(distinct) == 1 and clean,
        f"{len(versions)} stages; code versions: {[v[:12] + v[40:] for v in distinct]}",
    )


def run_checks(out: Path) -> int:
    report = Report()
    check_provenance(report, out)
    look, base = load(out, "lookback"), load(out, "baseline")
    check_inputs(report, look, base)
    check_accounting(report, "baseline", base)
    runs = {}
    for case in C.CASES:
        if not (out / f"case_{case}.npz").exists():
            report.add(f"{case}: output present", False, "missing; run the case stage")
            continue
        runs[case] = load(out, f"case_{case}")
        same_people = np.array_equal(runs[case]["person_id"], base["person_id"])
        report.add(f"{case}: same people in the same order as the baseline", same_people, "")
        check_accounting(report, case, runs[case])
        check_case(report, case, runs[case], base, look)
    # No Marketplace enrollee switches in these cases, so the credit must not move.
    for case in ("floor", "uninsured", "uninsured_wide"):
        if case in runs:
            check_no_marketplace_switch(report, case, runs[case], base)
    if "floor" in runs:
        check_floor(report, runs["floor"], base)
    check_nesting(report, runs, base)
    (out / "checks.json").write_text(json.dumps(report.rows, indent=1))
    print(f"\n{len(report.rows) - report.failed} passed, {report.failed} failed")
    return 1 if report.failed else 0
