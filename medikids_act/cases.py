"""Switching cases: who enrolls in Medicaid under the bill.

The model cannot say how many people would switch from private coverage, so
each case is a stated assumption, not a prediction. A case is a set of people
under 26. Everyone in the set enrolls. People outside it who are eligible only
through the new group stay as they are; people eligible through an existing
group keep the dataset's take-up flag.

Every case contains the floor, the modeled transitions (see ``transfers``).
Existing CHIP law moves ordinary separate-CHIP children found eligible for
Medicaid; the timing of that move, the take-up of Basic Health Program
enrollees and the move of CHIP pregnancy coverage are modeling assumptions. The chain floor, uninsured, marketplace,
employer_25, employer_50, everyone is nested, each case containing the one
before. Two side cases sit outside the chain: ``newborns`` (between the floor
and everyone) and ``uninsured_wide`` (between uninsured and everyone).

The cases are enrollment scenarios, not a timeline and not bounds on a later
year: automatic enrollment, applications and written opt-outs over time are
not modeled.
"""

from __future__ import annotations

import numpy as np

from medikids_act import assumptions as A
from medikids_act.coverage import Coverage, _household_draw

CHAIN = ("floor", "uninsured", "marketplace", "employer_25", "employer_50", "everyone")
SIDE_CASES = ("newborns", "uninsured_wide")
CASES = ("floor", *SIDE_CASES, *CHAIN[1:])

DESCRIPTIONS = {
    "floor": "Modeled transitions only: separate-CHIP enrollees under 26 (children and "
    "pregnancy coverage) and Basic Health Program enrollees under 26 are assumed to move to "
    "Medicaid on the start date, and people under 26 barred by the community engagement "
    "requirement regain Medicaid at their stored take-up.",
    "newborns": "The floor, plus every child under 1, each for a full year (an annualized "
    "illustration of enrollment at birth, not the first year's cost).",
    "uninsured": "The floor, plus everyone under 26 who is uninsured.",
    "uninsured_wide": "As uninsured, plus people under 26 who report Medicaid or CHIP but "
    "whom the model does not enroll (an enrollment sensitivity: many reported it only for "
    "the prior year, so their current coverage is unknown).",
    "marketplace": "As uninsured, plus everyone under 26 in the Marketplace class.",
    "employer_25": "As marketplace, plus people under 26 in the employer class who live in a "
    "random quarter of all households.",
    "employer_50": "As marketplace, plus people under 26 in the employer class who live in a "
    "random half of all households.",
    "everyone": "Everyone under 26 enrolls.",
}


def household_draw(household_id: np.ndarray, seed: int = A.SWITCH_SEED) -> np.ndarray:
    """A uniform draw in [0, 1) for each person, the same within a household.

    Households are ranked in a seeded random order and the draw is the rank
    divided by the number of households, so the set of households below any
    threshold grows as the threshold rises.
    """
    return _household_draw(household_id, seed)


def transfers(age: np.ndarray, coverage: np.ndarray) -> np.ndarray:
    """People the floor moves to Medicaid: modeled transitions, partly assumed.

    A child eligible for Medicaid cannot be a "targeted low-income child" for
    separate CHIP (SSA 2110(b)(1)(C)), and a person eligible to enroll in
    Medicaid is not an eligible individual for the Basic Health Program
    (ACA 1331(e)(1)). So both programs lose their eligibility under 26 once
    the new group starts. The estimate moves every such enrollee to Medicaid
    on the start date: for ordinary separate-CHIP children the move follows
    from existing CHIP law (its timing is assumed); for Basic Health Program
    enrollees and CHIP pregnancy coverage, including the from-conception
    option whose beneficiary is the unborn child, the move is assumed.
    """
    age = np.asarray(age)
    coverage = np.asarray(coverage)
    moved = np.isin(coverage, [int(Coverage.CHIP), int(Coverage.BASIC_HEALTH)])
    return moved & (age < A.AGE_LIMIT)


def case_enrolls(
    case: str,
    *,
    age: np.ndarray,
    coverage: np.ndarray,
    household_id: np.ndarray,
    seed: int = A.SWITCH_SEED,
) -> np.ndarray:
    """Boolean array: who enrolls in Medicaid in ``case``."""
    if case not in CASES:
        raise ValueError(f"unknown case {case!r}; expected one of {CASES}")
    age = np.asarray(age)
    coverage = np.asarray(coverage)
    under_26 = age < A.AGE_LIMIT
    enrolls = transfers(age, coverage)
    if case == "floor":
        return enrolls
    if case == "newborns":
        return enrolls | (age < 1)
    if case == "everyone":
        return under_26
    enrolls |= under_26 & (coverage == int(Coverage.UNINSURED))
    if case == "uninsured":
        return enrolls
    if case == "uninsured_wide":
        return enrolls | (under_26 & (coverage == int(Coverage.MEDICAID_REPORTED)))
    enrolls |= under_26 & (coverage == int(Coverage.MARKETPLACE))
    if case == "marketplace":
        return enrolls
    share = {
        "employer_25": A.EMPLOYER_SWITCH_SHARES[0],
        "employer_50": A.EMPLOYER_SWITCH_SHARES[1],
    }[case]
    draw = household_draw(household_id, seed)
    return enrolls | (under_26 & (coverage == int(Coverage.EMPLOYER)) & (draw < share))
