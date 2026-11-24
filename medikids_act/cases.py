"""Switching cases: who enrolls in Medicaid under the bill.

The model cannot say how many people would switch from private coverage, so
each case is a stated assumption, not a prediction. A case is a set of people
under 26. Everyone in the set enrolls. People outside it who are eligible only
through the new group stay as they are; people eligible through an existing
group keep the dataset's take-up flag.

Every case contains the floor: the people the bill moves with no choice of
their own (see ``transfers``). The chain floor, uninsured, marketplace,
employer_25, employer_50, everyone is nested, each case containing the one
before. ``newborns`` sits between the floor and everyone.

Read for the first year, a case says who opts in. Read for the steady state,
when every child has been enrolled at birth, the same case says who is left
after the rest have opted out.
"""

from __future__ import annotations

import numpy as np

from medikids_act import assumptions as A
from medikids_act.coverage import Coverage

CHAIN = ("floor", "uninsured", "marketplace", "employer_25", "employer_50", "everyone")
CASES = ("floor", "newborns", *CHAIN[1:])

DESCRIPTIONS = {
    "floor": "Nobody chooses to enroll. Only the moves the law forces: separate-CHIP "
    "children and Basic Health Program enrollees under 26 move to Medicaid.",
    "newborns": "The floor, plus every child under 1 (automatic enrollment at birth).",
    "uninsured": "The floor, plus everyone under 26 with no coverage.",
    "marketplace": "As above, plus everyone under 26 with Marketplace coverage.",
    "employer_25": "As above, plus the under-26 members of a random quarter of households "
    "with employer coverage.",
    "employer_50": "As above, with half of those households.",
    "everyone": "Everyone under 26 enrolls.",
}


def household_draw(household_id: np.ndarray, seed: int = A.SWITCH_SEED) -> np.ndarray:
    """A uniform draw in [0, 1) for each person, the same within a household.

    Households are ranked in a seeded random order and the draw is the rank
    divided by the number of households, so the set of households below any
    threshold grows as the threshold rises.
    """
    household_id = np.asarray(household_id)
    unique, inverse = np.unique(household_id, return_inverse=True)
    order = np.random.default_rng(seed).permutation(unique.size)
    return (order / unique.size)[inverse]


def transfers(age: np.ndarray, coverage: np.ndarray) -> np.ndarray:
    """People the bill moves to Medicaid whether or not anyone chooses to enroll.

    A child eligible for Medicaid cannot be a "targeted low-income child" for
    separate CHIP (SSA 2110(b)(1)(C)), and a person eligible to enroll in
    Medicaid is not an eligible individual for the Basic Health Program
    (ACA 1331(e)(1)). Both programs lose everyone under 26 the day the new
    group starts, and the estimate moves them to Medicaid.
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
    enrolls |= under_26 & (coverage == int(Coverage.MARKETPLACE))
    if case == "marketplace":
        return enrolls
    share = {
        "employer_25": A.EMPLOYER_SWITCH_SHARES[0],
        "employer_50": A.EMPLOYER_SWITCH_SHARES[1],
    }[case]
    draw = household_draw(household_id, seed)
    return enrolls | (under_26 & (coverage == int(Coverage.EMPLOYER)) & (draw < share))
