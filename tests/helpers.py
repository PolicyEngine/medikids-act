"""Names and helpers shared by the household test modules."""

from __future__ import annotations

from medikids_act import assumptions as A
from tests.conftest import HOUSEHOLDS, Y

UNDER_26 = [
    f"{name}.{person}"
    for name, (_, members) in HOUSEHOLDS.items()
    for person, age, _, _ in members
    if age < A.AGE_LIMIT
]


OLDER = [
    f"{name}.{person}"
    for name, (_, members) in HOUSEHOLDS.items()
    for person, age, _, _ in members
    if age >= A.AGE_LIMIT
]


COVERAGE_VARIABLES = (
    "is_medicaid_eligible",
    "medicaid_enrolled",
    "is_chip_eligible",
    "chip_enrolled",
    "is_basic_health_program_eligible",
    "pays_aca_premium",
    "is_medicaid_ineligible_due_to_work_requirement",
)


# --- The fixtures describe the households they claim to ----------------------


STATE_FUNDED = ("ny_undocumented.parent", "ny_undocumented.child")


FOSTER_YOUTH = "ca_foster.adult"


def fmap(run, state: str) -> float:
    """The state's regular match rate in the reporting year, from the engine."""
    rates = run.sim.tax_benefit_system.parameters.gov.hhs.medicaid.cost_share.fmap
    return float(getattr(rates, state)(f"{Y}-01-01"))


FULL, EXPANSION, REGULAR, NONE = "100 percent", "expansion rate", "regular rate", "no payment"


def rate(run, person: str, kind: str) -> float:
    state = HOUSEHOLDS[person.split(".")[0]][0]
    return {FULL: 1.0, EXPANSION: 0.9, REGULAR: fmap(run, state), NONE: 0.0}[kind]
