"""Build the result tables from the arrays the simulation stages wrote.

    python -m medikids_act.pipeline tables

Writes ``table_*.csv`` and ``summary.md`` to the results folder. Every figure
is a weighted sum, or a difference of weighted sums, over the outputs of the
runs for the scenario it describes. Nothing here scales, interpolates or
extrapolates from one run to another.

Units: people are counts; money is dollars a year in the reporting year.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from microdf import MicroSeries

from medikids_act import assumptions as A
from medikids_act import cases as C
from medikids_act.benchmarks import BY_KEY
from medikids_act.checks import load, weighted_sum
from medikids_act.coverage import SUMMARY_GROUPS, Coverage
from medikids_act.reform import READINGS

AGE_BANDS = (("Under 1", 0, 1), ("1 to 18", 1, 19), ("19 to 25", 19, 26))
PRICINGS = {
    "group_rate": ("medikids_group_rate_cost", "medikids_group_rate_federal_cost"),
    "engine": ("medicaid_cost", "medicaid_federal_cost"),
}


def _band(age: np.ndarray, low: int, high: int) -> np.ndarray:
    return (age >= low) & (age < high)


def _mean(values, weights, mask) -> float:
    mask = np.asarray(mask)
    if not mask.any():
        return float("nan")
    return float(
        MicroSeries(np.asarray(values, float)[mask], weights=np.asarray(weights)[mask]).mean()
    )


def coverage_table(base: dict) -> pd.DataFrame:
    age, weights, coverage = base["age"], base["person_weight"], base["coverage"]
    under_26 = age < A.AGE_LIMIT
    total = weighted_sum(under_26, weights)
    rows = []

    def row(label: str, mask: np.ndarray, kind: str) -> None:
        entry = {"row": label, "kind": kind}
        for name, low, high in AGE_BANDS:
            entry[name] = weighted_sum(mask & _band(age, low, high), weights)
        entry["Under 26"] = weighted_sum(mask & under_26, weights)
        entry["Share of people under 26"] = entry["Under 26"] / total
        rows.append(entry)

    for group, members in SUMMARY_GROUPS.items():
        row(group, np.isin(coverage, [int(m) for m in members]), "group")
    row("All people under 26", np.ones_like(under_26), "total")
    for member in Coverage:
        row(member.name, coverage == int(member), "class")
    ihs_only = (coverage == int(Coverage.UNINSURED)) & base[
        "has_indian_health_service_coverage_at_interview"
    ]
    row("Uninsured with Indian Health Service only", ihs_only, "memo")
    return pd.DataFrame(rows)


def eligibility_table(base: dict, look: dict) -> pd.DataFrame:
    age, weights = base["age"], base["person_weight"]
    under_26 = age < A.AGE_LIMIT
    eligible = base["is_medicaid_eligible"]
    chip = base["is_chip_eligible"]
    barred = base["is_medicaid_ineligible_due_to_work_requirement"]
    outside_plan = ~look["lookback_eligible"]
    definitions = {
        "People under 26": under_26,
        "Eligible for Medicaid under current law": under_26 & eligible,
        "... and enrolled": under_26 & base["medicaid_enrolled"],
        "Eligible for separate CHIP under current law": under_26 & chip,
        "Eligible for the Basic Health Program under current law": under_26
        & base["is_basic_health_program_eligible"],
        "Newly eligible for Medicaid under the bill": under_26 & ~eligible,
        "... of whom eligible for separate CHIP today": under_26 & ~eligible & chip,
        "... of whom barred today by the community engagement requirement": under_26
        & ~eligible
        & barred,
        "... of whom neither": under_26 & ~eligible & ~chip & ~barred,
        "Outside the 2025-01-01 State plan (would draw the 100 percent match)": under_26
        & outside_plan,
        "... of whom enrolled in Medicaid at baseline (state-funded coverage)": under_26
        & outside_plan
        & base["medicaid_enrolled"],
        "Inside the 2025-01-01 State plan": under_26 & ~outside_plan,
        "... of whom not eligible under current law in the reporting year": under_26
        & ~outside_plan
        & ~eligible,
    }
    rows = []
    for label, mask in definitions.items():
        entry = {"row": label}
        for name, low, high in AGE_BANDS:
            entry[name] = weighted_sum(mask & _band(age, low, high), weights)
        entry["Under 26"] = weighted_sum(mask, weights)
        rows.append(entry)
    return pd.DataFrame(rows)


def _totals(run: dict, base: dict) -> dict[str, float]:
    weights, unit_weights = base["person_weight"], base["tax_unit_weight"]
    under_26 = base["age"] < A.AGE_LIMIT
    out = {
        "enrolled_under_26": weighted_sum(run["medicaid_enrolled"] & under_26, weights),
        "chip": weighted_sum(run["chip"], weights),
        "chip_federal": weighted_sum(run["chip_federal_cost"], weights),
        "chip_state": weighted_sum(run["chip_state_cost"], weights),
        "premium_tax_credit": weighted_sum(run["tax_unit__assigned_aca_ptc"], unit_weights),
        "basic_health_program": weighted_sum(run["tax_unit__basic_health_program"], unit_weights),
    }
    for pricing, (cost, federal) in PRICINGS.items():
        out[f"{pricing}_cost"] = weighted_sum(run[cost], weights)
        out[f"{pricing}_federal"] = weighted_sum(run[federal], weights)
    return out


def cases_table(base: dict, runs: dict[str, dict]) -> pd.DataFrame:
    """Change from the baseline in each switching case, primary reading of the match."""
    weights = base["person_weight"]
    under_26 = base["age"] < A.AGE_LIMIT
    at_base = _totals(base, base)
    rows = []
    for case, run in runs.items():
        now = _totals(run, base)
        new = run["medicaid_enrolled"] & ~base["medicaid_enrolled"] & under_26
        row = {
            "case": case,
            "enrolled_under_26": now["enrolled_under_26"],
            "new_enrollees_under_26": weighted_sum(new, weights),
        }
        for pricing in PRICINGS:
            gross = now[f"{pricing}_cost"] - at_base[f"{pricing}_cost"]
            federal = now[f"{pricing}_federal"] - at_base[f"{pricing}_federal"]
            row[f"{pricing}_medicaid_change"] = gross
            row[f"{pricing}_medicaid_federal_change"] = federal
            row[f"{pricing}_medicaid_state_change"] = gross - federal
        row["chip_change"] = now["chip"] - at_base["chip"]
        row["chip_federal_change"] = now["chip_federal"] - at_base["chip_federal"]
        row["chip_state_change"] = now["chip_state"] - at_base["chip_state"]
        row["premium_tax_credit_change"] = now["premium_tax_credit"] - at_base["premium_tax_credit"]
        row["basic_health_program_change"] = (
            now["basic_health_program"] - at_base["basic_health_program"]
        )
        other_federal = (
            row["chip_federal_change"]
            + row["premium_tax_credit_change"]
            + row["basic_health_program_change"]
        )
        for pricing in PRICINGS:
            row[f"{pricing}_net_federal_change"] = (
                row[f"{pricing}_medicaid_federal_change"] + other_federal
            )
            row[f"{pricing}_net_state_change"] = (
                row[f"{pricing}_medicaid_state_change"] + row["chip_state_change"]
            )
        rows.append(row)
    return pd.DataFrame(rows)


def readings_table(base: dict, runs: dict[str, dict]) -> pd.DataFrame:
    """Federal and state Medicaid change under each reading of the bill's match rates."""
    weights = base["person_weight"]
    rows = []
    for case, run in runs.items():
        for pricing, (cost, federal) in PRICINGS.items():
            gross = weighted_sum(run[cost], weights) - weighted_sum(base[cost], weights)
            base_federal = weighted_sum(base[federal], weights)
            for reading in READINGS:
                prefix = "medikids_group_rate" if pricing == "group_rate" else "medikids_medicaid"
                key = federal if reading == "primary" else f"{prefix}_federal_cost_{reading}"
                change = weighted_sum(run[key], weights) - base_federal
                rows.append(
                    {
                        "case": case,
                        "pricing": pricing,
                        "reading": reading,
                        "medicaid_change": gross,
                        "medicaid_federal_change": change,
                        "medicaid_state_change": gross - change,
                    }
                )
    return pd.DataFrame(rows)


def per_enrollee_table(base: dict, everyone: dict) -> pd.DataFrame:
    """Average cost of a new enrollee under each pricing (the everyone case)."""
    age, weights = base["age"], base["person_weight"]
    under_26 = age < A.AGE_LIMIT
    new = everyone["medicaid_enrolled"] & ~base["medicaid_enrolled"] & under_26
    kept = everyone["medicaid_enrolled"] & base["medicaid_enrolled"] & under_26
    rows = []
    for name, low, high in (*AGE_BANDS, ("Under 26", 0, A.AGE_LIMIT)):
        band = _band(age, low, high)
        for label, mask in (("New enrollees", new & band), ("Enrolled at baseline", kept & band)):
            rows.append(
                {
                    "group": label,
                    "age": name,
                    "people": weighted_sum(mask, weights),
                    "average_cost_group_rate": _mean(
                        everyone["medikids_group_rate_cost"], weights, mask
                    ),
                    "average_cost_engine": _mean(everyone["medicaid_cost"], weights, mask),
                    "average_federal_share": _mean(
                        everyone["medicaid_federal_share"], weights, mask
                    ),
                }
            )
    return pd.DataFrame(rows)


def floor_table(base: dict, floor: dict, look: dict) -> pd.DataFrame:
    """What the floor case moves, by the reason for the move."""
    age, weights, coverage = base["age"], base["person_weight"], base["coverage"]
    under_26 = age < A.AGE_LIMIT
    new = floor["medicaid_enrolled"] & ~base["medicaid_enrolled"] & under_26
    state_funded = base["medicaid_enrolled"] & under_26 & (base["medicaid_federal_share"] <= 0)
    groups = {
        "Separate-CHIP enrollees moved to Medicaid": new & (coverage == int(Coverage.CHIP)),
        "Basic Health Program enrollees moved to Medicaid": new
        & (coverage == int(Coverage.BASIC_HEALTH)),
        "Regain Medicaid through the community engagement exception": new
        & ~np.isin(coverage, [int(Coverage.CHIP), int(Coverage.BASIC_HEALTH)]),
        "Already enrolled in state-funded coverage (match moves to federal)": state_funded,
    }
    rows = []
    for label, mask in groups.items():
        row = {"row": label, "people": weighted_sum(mask, weights)}
        for pricing, (cost, federal) in PRICINGS.items():
            row[f"{pricing}_cost_under_bill"] = weighted_sum(floor[cost], weights, mask)
            row[f"{pricing}_federal_under_bill"] = weighted_sum(floor[federal], weights, mask)
            row[f"{pricing}_federal_at_baseline"] = weighted_sum(base[federal], weights, mask)
        row["outside_2025_plan"] = weighted_sum(mask & ~look["lookback_eligible"], weights)
        rows.append(row)
    return pd.DataFrame(rows)


def benchmark_table(base: dict, look: dict) -> pd.DataFrame:
    """The model's baseline beside outside figures. Definitions differ; both are stated."""
    age, weights, coverage = base["age"], base["person_weight"], base["coverage"]
    data_weights = look["base_person_weight"]
    under_19, young_adult = age < A.CHILD_AGE_LIMIT, _band(age, 19, 26)
    under_26 = age < A.AGE_LIMIT
    unit_weights = base["tax_unit_weight"]

    def count(mask, w=weights):
        return weighted_sum(mask, w)

    model = {
        "population_under_26": (
            count(under_26, data_weights),
            "People under 26 at the dataset's own (2024) weights",
        ),
        "population_under_19": (count(under_19, data_weights), "Under 19, 2024 weights"),
        "population_19_to_25": (count(young_adult, data_weights), "19 to 25, 2024 weights"),
        "medicaid_chip_child_enrollment": (
            count(
                under_19 & (look["lookback_enrolled"] | look["lookback_separate_chip"]),
                data_weights,
            ),
            (
                "Under 19 enrolled in Medicaid or eligible for separate CHIP under the "
                "2025-01-01 rules, 2024 weights"
            ),
        ),
        "separate_chip_ever_enrolled": (
            count(under_19 & look["lookback_separate_chip"], data_weights),
            (
                "Under 19 eligible for separate CHIP under the 2025-01-01 rules, 2024 weights "
                "(the model enrolls every eligible child)"
            ),
        ),
        "separate_chip_spending": (
            weighted_sum(base["chip"], weights) / A.chip_growth(),
            (
                "Baseline separate-CHIP spending in the reporting year with the growth "
                "assumption divided back out"
            ),
        ),
        "cbo_children_federal_2029": (
            weighted_sum(base["medikids_group_rate_federal_cost"], weights, under_19),
            (
                "Baseline federal Medicaid cost of enrollees under 19 at group rates, "
                "reporting year (includes children eligible on disability)"
            ),
        ),
        "cbo_children_enrollment_2029": (
            count(under_19 & base["medicaid_enrolled"]),
            "Baseline Medicaid enrollees under 19, reporting year",
        ),
        "nhe_medicaid_spending_2029": (
            weighted_sum(base["medicaid_cost"], weights),
            "Baseline Medicaid cost of all enrollees at the engine's pricing, reporting year",
        ),
        "nhe_medicaid_enrollment_2029": (
            count(base["medicaid_enrolled"]),
            "Baseline Medicaid enrollees of all ages, reporting year",
        ),
        "uninsured_under_19": (
            count(under_19 & (coverage == int(Coverage.UNINSURED))),
            "Uninsured class under 19, reporting-year baseline",
        ),
        "uninsured_19_to_25": (
            count(young_adult & (coverage == int(Coverage.UNINSURED))),
            "Uninsured class at 19 to 25, reporting-year baseline",
        ),
        "employer_under_19": (
            count(under_19 & base["has_esi"]),
            "Under 19 reporting employer coverage (whatever their class)",
        ),
        "employer_19_to_25": (
            count(young_adult & base["has_esi"]),
            "19 to 25 reporting employer coverage (whatever their class)",
        ),
        "marketplace_under_26": (
            count(under_26 & (coverage == int(Coverage.MARKETPLACE))),
            "Marketplace class under 26, reporting-year baseline",
        ),
        "basic_health_program_under_26": (
            count(under_26 & (coverage == int(Coverage.BASIC_HEALTH))),
            "Basic Health Program class under 26, reporting-year baseline",
        ),
    }
    rows = []
    for key, (value, definition) in model.items():
        benchmark = BY_KEY[key]
        rows.append(
            {
                "key": key,
                "model": value,
                "model_definition": definition,
                "benchmark": benchmark.value,
                "benchmark_year": benchmark.year,
                "benchmark_definition": benchmark.definition,
                "benchmark_source": benchmark.source,
                "model_over_benchmark": value / benchmark.value,
            }
        )
    rows.append(
        {
            "key": "premium_tax_credit_baseline",
            "model": weighted_sum(base["tax_unit__assigned_aca_ptc"], unit_weights),
            "model_definition": "Baseline premium tax credits, all ages, reporting year",
        }
    )
    return pd.DataFrame(rows)


def by_state_table(base: dict, runs: dict[str, dict]) -> pd.DataFrame:
    age, weights, state = base["age"], base["person_weight"], base["state_code_str"]
    under_26 = age < A.AGE_LIMIT
    rows = []
    for code in np.unique(state):
        here = state == code
        row = {"state": code, "people_under_26": weighted_sum(under_26 & here, weights)}
        for case in ("floor", "uninsured", "everyone"):
            if case not in runs:
                continue
            run = runs[case]
            new = run["medicaid_enrolled"] & ~base["medicaid_enrolled"] & under_26 & here
            row[f"{case}_new_enrollees"] = weighted_sum(new, weights)
            for pricing, (cost, federal) in PRICINGS.items():
                gross = weighted_sum(run[cost], weights, here) - weighted_sum(
                    base[cost], weights, here
                )
                fed = weighted_sum(run[federal], weights, here) - weighted_sum(
                    base[federal], weights, here
                )
                row[f"{case}_{pricing}_medicaid_change"] = gross
                row[f"{case}_{pricing}_federal_change"] = fed
                row[f"{case}_{pricing}_state_change"] = gross - fed
        rows.append(row)
    return pd.DataFrame(rows)


def _billions(value: float) -> str:
    return f"{value / 1e9:,.1f}"


def _millions(value: float) -> str:
    return f"{value / 1e6:,.2f}"


def render_summary(tables: dict[str, pd.DataFrame], meta: dict, checks: list | None) -> str:
    lines = [
        "# MediKids Act (S. 5037): draft result tables",
        "",
        "Draft for review. Not for publication.",
        "",
        (
            f"Reporting year {A.YEAR}. policyengine {meta['versions']['policyengine']}, "
            f"policyengine-us {meta['versions']['policyengine-us']}, dataset {meta['dataset']} "
            f"({meta['data_build']})."
        ),
    ]
    if checks is not None:
        failed = [c for c in checks if not c["passed"]]
        lines.append(f"Invariant checks: {len(checks) - len(failed)} passed, {len(failed)} failed.")
    lines += ["", "## People under 26 by current coverage (millions)", ""]
    cov = tables["coverage"]
    bands = [name for name, _, _ in AGE_BANDS] + ["Under 26"]
    lines.append("| | " + " | ".join(bands) + " | Share |")
    lines.append("|---|" + "---:|" * (len(bands) + 1))
    for _, r in cov[cov["kind"].isin(["group", "total"])].iterrows():
        cells = " | ".join(_millions(r[b]) for b in bands)
        lines.append(f"| {r['row']} | {cells} | {r['Share of people under 26']:.1%} |")
    lines += ["", "Detail by class (millions under 26): "]
    for _, r in cov[cov["kind"].isin(["class", "memo"])].iterrows():
        lines.append(f"- {r['row']}: {_millions(r['Under 26'])}")
    lines += ["", "## Eligibility (millions)", "", "| | " + " | ".join(bands) + " |"]
    lines.append("|---|" + "---:|" * len(bands))
    for _, r in tables["eligibility"].iterrows():
        lines.append(f"| {r['row']} | " + " | ".join(_millions(r[b]) for b in bands) + " |")
    cases = tables["cases"]
    for pricing, title in (
        ("group_rate", "MACPAC group rates"),
        ("engine", "the engine's allocation"),
    ):
        lines += [
            "",
            f"## Change from baseline by switching case, priced at {title} ($ billions)",
            "",
            (
                "| Case | Enrolled under 26 (m) | New enrollees (m) | Medicaid | Federal | State | "
                "CHIP replaced | Premium tax credits | Basic Health Program | Net federal | Net state |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for _, r in cases.iterrows():
            lines.append(
                f"| {r['case']} | {_millions(r['enrolled_under_26'])} | "
                f"{_millions(r['new_enrollees_under_26'])} | "
                f"{_billions(r[f'{pricing}_medicaid_change'])} | "
                f"{_billions(r[f'{pricing}_medicaid_federal_change'])} | "
                f"{_billions(r[f'{pricing}_medicaid_state_change'])} | "
                f"{_billions(r['chip_change'])} | {_billions(r['premium_tax_credit_change'])} | "
                f"{_billions(r['basic_health_program_change'])} | "
                f"{_billions(r[f'{pricing}_net_federal_change'])} | "
                f"{_billions(r[f'{pricing}_net_state_change'])} |"
            )
    lines += [
        "",
        "## Federal and state Medicaid change under each reading of the match ($ billions)",
        "",
        "| Case | Pricing | Reading | Medicaid | Federal | State |",
        "|---|---|---|---:|---:|---:|",
    ]
    for _, r in tables["readings"].iterrows():
        lines.append(
            f"| {r['case']} | {r['pricing']} | {r['reading']} | {_billions(r['medicaid_change'])} | "
            f"{_billions(r['medicaid_federal_change'])} | {_billions(r['medicaid_state_change'])} |"
        )
    lines += [
        "",
        "## Average cost per enrollee in the everyone case (dollars)",
        "",
        "| Group | Age | People (m) | Group rate | Engine | Average federal share |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for _, r in tables["per_enrollee"].iterrows():
        lines.append(
            f"| {r['group']} | {r['age']} | {_millions(r['people'])} | "
            f"{r['average_cost_group_rate']:,.0f} | {r['average_cost_engine']:,.0f} | "
            f"{r['average_federal_share']:.1%} |"
        )
    lines += [
        "",
        "## What the floor case moves",
        "",
        (
            "| | People (m) | Outside 2025 plan (m) | Group rate cost ($bn) | Federal under bill | "
            "Federal at baseline | Engine cost ($bn) | Federal under bill | Federal at baseline |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in tables["floor"].iterrows():
        lines.append(
            f"| {r['row']} | {_millions(r['people'])} | {_millions(r['outside_2025_plan'])} | "
            f"{_billions(r['group_rate_cost_under_bill'])} | "
            f"{_billions(r['group_rate_federal_under_bill'])} | "
            f"{_billions(r['group_rate_federal_at_baseline'])} | "
            f"{_billions(r['engine_cost_under_bill'])} | {_billions(r['engine_federal_under_bill'])} | "
            f"{_billions(r['engine_federal_at_baseline'])} |"
        )
    lines += [
        "",
        "## Benchmarks",
        "",
        "| Measure | Model | Benchmark | Model / benchmark | Model definition | Benchmark definition |",
        "|---|---:|---:|---:|---|---|",
    ]
    for _, r in tables["benchmarks"].iterrows():
        if pd.isna(r.get("benchmark")):
            lines.append(f"| {r['key']} | {r['model']:,.0f} | | | {r['model_definition']} | |")
            continue
        lines.append(
            f"| {r['key']} | {r['model']:,.0f} | {r['benchmark']:,.0f} | "
            f"{r['model_over_benchmark']:.2f} | {r['model_definition']} | "
            f"{r['benchmark_definition']} ({r['benchmark_year']}; {r['benchmark_source']}) |"
        )
    return "\n".join(lines) + "\n"


def write_tables(out: Path) -> None:
    look, base = load(out, "lookback"), load(out, "baseline")
    runs = {c: load(out, f"case_{c}") for c in C.CASES if (out / f"case_{c}.npz").exists()}
    tables = {
        "coverage": coverage_table(base),
        "eligibility": eligibility_table(base, look),
        "cases": cases_table(base, runs),
        "readings": readings_table(base, runs),
        "benchmarks": benchmark_table(base, look),
        "by_state": by_state_table(base, runs),
    }
    if "everyone" in runs:
        tables["per_enrollee"] = per_enrollee_table(base, runs["everyone"])
    if "floor" in runs:
        tables["floor"] = floor_table(base, runs["floor"], look)
    for name, table in tables.items():
        table.to_csv(out / f"table_{name}.csv", index=False)
    meta = json.loads((out / "baseline.json").read_text())
    checks_path = out / "checks.json"
    checks = json.loads(checks_path.read_text()) if checks_path.exists() else None
    if {"per_enrollee", "floor"} <= tables.keys():
        (out / "summary.md").write_text(render_summary(tables, meta, checks))
    print(f"wrote {len(tables)} tables to {out}")
