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
    counts = np.bincount(base["coverage"], minlength=len(Coverage))
    by_class = sum(
        weighted_sum((base["coverage"] == int(c)) & under_26, base["person_weight"])
        for c in Coverage
    )
    report.add(
        "coverage classes partition the population under 26",
        counts.sum() == base["coverage"].size and abs(by_class / population - 1) < 1e-9,
        f"{counts.sum()} of {base['coverage'].size} people classified; class counts sum to "
        f"the total within {abs(by_class / population - 1):.1e}",
    )


def check_accounting(report: Report, name: str, run: dict) -> None:
    # The engine computes in single precision, so the identity holds to a few
    # parts in ten million of each person's cost.
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
    over = run["medikids_group_rate_federal_cost"] - run["medikids_group_rate_cost"]
    report.add(
        f"{name}: federal group-rate cost never exceeds the group-rate cost",
        bool((over <= DOLLAR_TOLERANCE).all()),
        f"largest excess ${max(float(over.max()), 0):.4f}",
    )


def check_case(report: Report, case: str, run: dict, base: dict, look: dict) -> None:
    under_26 = base["age"] < A.AGE_LIMIT
    enrolled = run["medicaid_enrolled"]
    base_enrolled = base["medicaid_enrolled"]

    moved = np.isin(base["coverage"], [int(Coverage.CHIP), int(Coverage.BASIC_HEALTH)]) & under_26
    report.add(
        f"{case}: no separate-CHIP or Basic Health Program enrollee under 26 is left uncovered",
        bool(enrolled[moved].all()),
        f"{int((~enrolled[moved]).sum())} of {int(moved.sum())} not enrolled in Medicaid",
    )
    report.add(
        f"{case}: everyone the case names is enrolled",
        bool(enrolled[run["case_enrolls"]].all()),
        f"{int((~enrolled[run['case_enrolls']]).sum())} named but not enrolled",
    )
    report.add(
        f"{case}: nobody under 26 enrolled at baseline loses Medicaid",
        bool(enrolled[base_enrolled & under_26].all()),
        f"{int((~enrolled[base_enrolled & under_26]).sum())} lost enrollment",
    )
    older = ~under_26
    report.add(
        f"{case}: Medicaid enrollment at 26 and over is unchanged",
        bool((enrolled[older] == base_enrolled[older]).all()),
        f"{int((enrolled[older] != base_enrolled[older]).sum())} people changed",
    )
    # Outside family-tier states a person's price does not depend on who else
    # enrolls, so anyone enrolled in both runs must cost the same in both.
    both = enrolled & base_enrolled & ~base["family_tier"]
    gap = _max_abs(run["medicaid_cost"], base["medicaid_cost"], both)
    scale = max(float(np.abs(base["medicaid_cost"][both]).max()) if both.any() else 1.0, 1.0)
    report.add(
        f"{case}: people enrolled in both runs cost the same (outside family-tier states)",
        gap <= RELATIVE_TOLERANCE * scale + DOLLAR_TOLERANCE,
        f"largest gap ${gap:.4f} among {int(both.sum())} people",
    )
    gap = _max_abs(
        run["medikids_group_rate_cost"], base["medikids_group_rate_cost"], enrolled & base_enrolled
    )
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
    share = run["medicaid_federal_share"]
    full = enrolled & (share >= 1 - 1e-9)
    allowed = under_26 & ~look["lookback_eligible"]
    report.add(
        f"{case}: the 100 percent match goes only to people under 26 outside the 2025 plan",
        bool(allowed[full].all()),
        f"{int((~allowed[full]).sum())} people draw 100 percent without qualifying",
    )
    primary = run["medicaid_federal_cost"]
    ordered = (
        (run["medikids_medicaid_federal_cost_strict_v5"] <= primary + DOLLAR_TOLERANCE)
        & (run["medikids_medicaid_federal_cost_adult_group_100"] >= primary - DOLLAR_TOLERANCE)
        & (run["medikids_medicaid_federal_cost_adult_group_regular"] <= primary + DOLLAR_TOLERANCE)
    )
    report.add(
        f"{case}: the alternative readings bracket the primary one as their definitions imply",
        bool(ordered.all()),
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
    gap = _max_abs(run["tax_unit__assigned_aca_ptc"], base["tax_unit__assigned_aca_ptc"])
    report.add(
        f"{case}: premium tax credits equal the baseline for every tax unit",
        gap <= DOLLAR_TOLERANCE,
        f"largest gap ${gap:.4f} across {base['tax_unit__assigned_aca_ptc'].size} tax units",
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
    under_26 = base["age"] < A.AGE_LIMIT
    new = floor["medicaid_enrolled"] & ~base["medicaid_enrolled"]
    moved = np.isin(base["coverage"], [int(Coverage.CHIP), int(Coverage.BASIC_HEALTH)]) & under_26
    excepted = base["is_medicaid_ineligible_due_to_work_requirement"] & under_26
    explained = moved | excepted
    report.add(
        "floor: every new enrollee is a forced move or regains Medicaid through the "
        "community engagement exception",
        bool(explained[new].all()),
        f"{int((~explained[new]).sum())} of {int(new.sum())} new enrollees unexplained",
    )
    weights = base["person_weight"]
    plain = ~base["family_tier"]
    change = weighted_sum(floor["medicaid_cost"], weights, plain) - weighted_sum(
        base["medicaid_cost"], weights, plain
    )
    added = weighted_sum(floor["medicaid_cost"], weights, new & plain)
    scale = max(abs(added), 1.0)
    report.add(
        "floor: Medicaid spending is the baseline plus the new enrollees (outside "
        "family-tier states)",
        abs(change - added) <= 1e-6 * scale,
        f"relative gap {abs(change - added) / scale:.2e}",
    )


def check_nesting(report: Report, runs: dict[str, dict], base: dict) -> None:
    weights = base["person_weight"]
    unit_weights = base["tax_unit_weight"]
    orders = [C.CHAIN, ("floor", "newborns", "everyone")]
    for order in orders:
        present = [c for c in order if c in runs]
        for earlier, later in itertools.pairwise(present):
            a, b = runs[earlier], runs[later]
            subset = bool((~a["medicaid_enrolled"] | b["medicaid_enrolled"]).all())
            report.add(
                f"{earlier} -> {later}: enrollment is nested",
                subset,
                f"{int((a['medicaid_enrolled'] & ~b['medicaid_enrolled']).sum())} people "
                "enrolled in the smaller case only",
            )
            for label, key in (
                ("Medicaid cost at the engine's pricing", "medicaid_cost"),
                ("Medicaid cost at group rates", "medikids_group_rate_cost"),
                ("federal Medicaid cost at the engine's pricing", "medicaid_federal_cost"),
                ("federal Medicaid cost at group rates", "medikids_group_rate_federal_cost"),
            ):
                lo, hi = weighted_sum(a[key], weights), weighted_sum(b[key], weights)
                report.add(
                    f"{earlier} -> {later}: {label} does not fall",
                    hi >= lo - 1e-9 * max(abs(lo), 1.0),
                    "rises or holds" if hi >= lo else f"falls by a relative {(lo - hi) / lo:.2e}",
                )
            lo = weighted_sum(a["tax_unit__assigned_aca_ptc"], unit_weights)
            hi = weighted_sum(b["tax_unit__assigned_aca_ptc"], unit_weights)
            report.add(
                f"{earlier} -> {later}: premium tax credits do not rise",
                hi <= lo + 1e-9 * max(abs(lo), 1.0),
                "fall or hold" if hi <= lo else f"rise by a relative {(hi - lo) / lo:.2e}",
            )


def run_checks(out: Path) -> int:
    report = Report()
    look, base = load(out, "lookback"), load(out, "baseline")
    check_inputs(report, look, base)
    check_accounting(report, "baseline", base)
    runs = {}
    for case in C.CASES:
        if not (out / f"case_{case}.npz").exists():
            report.add(f"{case}: output present", False, "missing; run the case stage")
            continue
        runs[case] = load(out, f"case_{case}")
        same_people = np.array_equal(runs[case]["person_household_id"], base["person_household_id"])
        report.add(f"{case}: same people in the same order as the baseline", same_people, "")
        check_accounting(report, case, runs[case])
        check_case(report, case, runs[case], base, look)
    for case in ("floor", "uninsured"):
        if case in runs:
            check_no_marketplace_switch(report, case, runs[case], base)
    if "floor" in runs:
        check_floor(report, runs["floor"], base)
    check_nesting(report, runs, base)
    assert set(READINGS) >= {"primary"}
    (out / "checks.json").write_text(json.dumps(report.rows, indent=1))
    print(f"\n{len(report.rows) - report.failed} passed, {report.failed} failed")
    return 1 if report.failed else 0
