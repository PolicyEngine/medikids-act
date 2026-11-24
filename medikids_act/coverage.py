"""Current coverage of each person, as one of eight mutually exclusive classes.

The engine has no "uninsured" variable. This module builds one from two kinds
of evidence: enrollment the model computes (Medicaid, CHIP, the Basic Health
Program, subsidized Marketplace coverage, Medicare) and coverage people
reported in the survey. A person is uninsured here if neither kind shows any
coverage.

The classes are assigned in the order below, so a person who fits two of them
gets the earlier one. Modeled public enrollment comes first because the cost
accounting follows it.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np


class Coverage(IntEnum):
    MEDICAID = 0  # modeled Medicaid enrollment
    CHIP = 1  # modeled separate-CHIP enrollment
    BASIC_HEALTH = 2  # modeled Basic Health Program enrollment
    EMPLOYER = 3  # reports employer coverage
    MARKETPLACE = 4  # modeled premium tax credit recipient, or reports Marketplace coverage
    MEDICAID_REPORTED = 5  # reports Medicaid or CHIP, but the model does not enroll them
    OTHER = 6  # other reported coverage, or modeled Medicare
    UNINSURED = 7  # none of the above (includes people with Indian Health Service only)


# The five groups the estimate reports.
SUMMARY_GROUPS = {
    "Medicaid or CHIP": (Coverage.MEDICAID, Coverage.CHIP, Coverage.MEDICAID_REPORTED),
    "Employer": (Coverage.EMPLOYER,),
    "Marketplace": (Coverage.MARKETPLACE,),
    "Other": (Coverage.BASIC_HEALTH, Coverage.OTHER),
    "Uninsured": (Coverage.UNINSURED,),
}

# Engine variables read to build the classes. Each is a person-level boolean in
# the current-law run; `takes_up_aca_if_eligible` is not needed because
# `person_receives_aca` already includes it.
MODELED = (
    "medicaid_enrolled",
    "chip_enrolled",
    "basic_health_program_enrolled",
    "person_receives_aca",
    "medicare_enrolled",
)
REPORTED_EMPLOYER = "has_esi"
REPORTED_MARKETPLACE = "has_marketplace_health_coverage_at_interview"
REPORTED_MEDICAID = "has_medicaid_health_coverage_at_interview"
REPORTED_OTHER = (
    "has_non_marketplace_direct_purchase_health_coverage_at_interview",
    "has_other_means_tested_health_coverage_at_interview",
    "has_tricare_health_coverage_at_interview",
    "has_champva_health_coverage_at_interview",
    "has_va_health_coverage_at_interview",
)
INDIAN_HEALTH_SERVICE = "has_indian_health_service_coverage_at_interview"
INPUTS = (
    *MODELED,
    REPORTED_EMPLOYER,
    REPORTED_MARKETPLACE,
    REPORTED_MEDICAID,
    *REPORTED_OTHER,
)


def classify(flags: dict[str, np.ndarray]) -> np.ndarray:
    """Assign each person one coverage class.

    ``flags`` maps every name in ``INPUTS`` to a boolean array, one value per
    person. Returns an integer array of ``Coverage`` values.
    """
    missing = [name for name in INPUTS if name not in flags]
    if missing:
        raise KeyError(f"missing coverage inputs: {missing}")
    f = {name: np.asarray(flags[name]).astype(bool) for name in INPUTS}
    other = f["medicare_enrolled"].copy()
    for name in REPORTED_OTHER:
        other |= f[name]
    conditions = [
        f["medicaid_enrolled"],
        f["chip_enrolled"],
        f["basic_health_program_enrolled"],
        f[REPORTED_EMPLOYER],
        f["person_receives_aca"] | f[REPORTED_MARKETPLACE],
        f[REPORTED_MEDICAID],
        other,
    ]
    choices = [
        Coverage.MEDICAID,
        Coverage.CHIP,
        Coverage.BASIC_HEALTH,
        Coverage.EMPLOYER,
        Coverage.MARKETPLACE,
        Coverage.MEDICAID_REPORTED,
        Coverage.OTHER,
    ]
    return np.select(conditions, [int(c) for c in choices], default=int(Coverage.UNINSURED))


def summary_group(coverage: np.ndarray) -> np.ndarray:
    """Map coverage classes to the five reported groups (as their names)."""
    coverage = np.asarray(coverage)
    out = np.empty(coverage.shape, dtype=object)
    for name, members in SUMMARY_GROUPS.items():
        out[np.isin(coverage, [int(m) for m in members])] = name
    return out
