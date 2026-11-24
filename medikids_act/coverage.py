"""Current coverage of each person, as one of eight mutually exclusive classes.

The engine has no "uninsured" variable, and the certified dataset records
coverage unevenly. It pools three survey years. Employer and Marketplace
coverage at the interview are on every record. Whether the person was
uninsured at the interview, and whether they then had Medicaid, direct-purchase
or military coverage, is recorded only on records from the latest survey year.
The other records carry coverage during the prior calendar year instead, for
Medicaid, Medicare and military coverage only.

So the classes are built in two steps.

1. Every record: modeled public enrollment first, because the cost accounting
   follows it, then reported employer coverage, then Marketplace coverage.
2. Whoever is left:
   - on a record with the interview items, the survey's own answer decides:
     uninsured at the interview, or covered by something else;
   - on a record without them, the person is uninsured with the probability
     measured among comparable people on records that have the items (same age
     band, same answer on Medicaid in the prior year), by a seeded draw shared
     within a household.

"Uninsured" therefore means uninsured at the interview and not enrolled in a
public program in the model. It is measured on part of the sample and imputed
at the measured rate on the rest.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np
from microdf import MicroSeries

from medikids_act import assumptions as A


class Coverage(IntEnum):
    MEDICAID = 0  # modeled Medicaid enrollment
    CHIP = 1  # modeled separate-CHIP enrollment
    BASIC_HEALTH = 2  # modeled Basic Health Program enrollment
    EMPLOYER = 3  # reports employer coverage at the interview
    MARKETPLACE = 4  # modeled premium tax credit recipient, or reports Marketplace coverage
    MEDICAID_REPORTED = 5  # reports Medicaid or CHIP, but the model does not enroll them
    OTHER = 6  # other coverage: military, Medicare, direct purchase, or covered but unrecorded
    UNINSURED = 7  # uninsured at the interview (measured, or imputed at the measured rate)


# The five groups the estimate reports.
SUMMARY_GROUPS = {
    "Medicaid or CHIP": (Coverage.MEDICAID, Coverage.CHIP, Coverage.MEDICAID_REPORTED),
    "Employer": (Coverage.EMPLOYER,),
    "Marketplace": (Coverage.MARKETPLACE,),
    "Other": (Coverage.BASIC_HEALTH, Coverage.OTHER),
    "Uninsured": (Coverage.UNINSURED,),
}

# Person-level booleans from the current-law run. `person_receives_aca`
# already includes the tax unit's take-up.
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
INDIAN_HEALTH_SERVICE = "has_indian_health_service_coverage_at_interview"
ENGINE_INPUTS = (*MODELED, REPORTED_EMPLOYER, REPORTED_MARKETPLACE, REPORTED_MEDICAID)

# Survey items read straight from the dataset's person table. The engine has no
# variable for them. Codes follow the Current Population Survey: 1 is yes.
#   NOW_COV  any coverage at the interview (1 yes, 2 no); missing on records
#            from the earlier survey years
#   CAID     Medicaid or CHIP at any time in the prior calendar year
#   MCARE    Medicare, MIL military coverage, CHAMPVA: the same, prior year
SURVEY_COLUMNS = ("NOW_COV", "CAID", "MCARE", "MIL", "CHAMPVA")
SURVEY_INPUTS = (
    "interview_items_present",
    "uninsured_at_interview",
    "medicaid_last_year",
    "other_public_last_year",
)
INPUTS = (*ENGINE_INPUTS, *SURVEY_INPUTS)

AGE_BANDS = (0, A.CHILD_AGE_LIMIT, A.AGE_LIMIT, 65)


def survey_inputs(columns: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Turn the raw survey columns into the booleans ``classify`` reads."""
    now_cov = np.asarray(columns["NOW_COV"], dtype=float)
    present = ~np.isnan(now_cov)
    other = np.zeros(now_cov.shape, dtype=bool)
    for name in ("MCARE", "MIL", "CHAMPVA"):
        other |= np.asarray(columns[name]) == 1
    return {
        "interview_items_present": present,
        "uninsured_at_interview": present & (now_cov == 2),
        "medicaid_last_year": np.asarray(columns["CAID"]) == 1,
        "other_public_last_year": other,
    }


def _household_draw(household_id: np.ndarray, seed: int) -> np.ndarray:
    """A uniform draw in [0, 1) per person, shared within a household."""
    unique, inverse = np.unique(np.asarray(household_id), return_inverse=True)
    order = np.random.default_rng(seed).permutation(unique.size)
    return (order / unique.size)[inverse]


def classify(
    flags: dict[str, np.ndarray],
    *,
    age: np.ndarray,
    weights: np.ndarray,
    household_id: np.ndarray,
    seed: int = A.UNINSURED_SEED,
) -> tuple[np.ndarray, dict]:
    """Assign each person one coverage class.

    ``flags`` maps every name in ``INPUTS`` to a boolean array, one value per
    person. Returns the classes as an integer array of ``Coverage`` values, and
    a record of the imputation: the measured uninsured share in each cell and
    which people were classified by measurement and which by imputation.
    """
    missing = [name for name in INPUTS if name not in flags]
    if missing:
        raise KeyError(f"missing coverage inputs: {missing}")
    f = {name: np.asarray(flags[name]).astype(bool) for name in INPUTS}
    age = np.asarray(age, dtype=float)
    weights = np.asarray(weights, dtype=float)
    present = f["interview_items_present"]

    first = [
        (f["medicaid_enrolled"], Coverage.MEDICAID),
        (f["chip_enrolled"], Coverage.CHIP),
        (f["basic_health_program_enrolled"], Coverage.BASIC_HEALTH),
        (f[REPORTED_EMPLOYER], Coverage.EMPLOYER),
        (f["person_receives_aca"] | f[REPORTED_MARKETPLACE], Coverage.MARKETPLACE),
    ]
    coverage = np.select(
        [condition for condition, _ in first], [int(c) for _, c in first], default=-1
    )
    rest = coverage == -1

    # Records with the interview items: the survey's own answer decides.
    measured = rest & present
    reports_medicaid = f[REPORTED_MEDICAID] | f["medicaid_last_year"]
    coverage[measured] = np.select(
        [f["uninsured_at_interview"][measured], reports_medicaid[measured]],
        [int(Coverage.UNINSURED), int(Coverage.MEDICAID_REPORTED)],
        default=int(Coverage.OTHER),
    )

    # Records without them: Medicare or military coverage in the prior year
    # counts as other coverage; everyone else is uninsured at the rate measured
    # in their cell.
    unmeasured = rest & ~present
    other_public = f["medicare_enrolled"] | f["other_public_last_year"]
    band = np.digitize(age, AGE_BANDS[1:])
    cell = band * 2 + f["medicaid_last_year"]
    comparable = measured & ~other_public
    rates = {}
    probability = np.zeros(age.shape)
    for value in np.unique(cell[unmeasured & ~other_public]):
        in_cell = comparable & (cell == value)
        if weights[in_cell].sum() > 0:
            share = float(
                MicroSeries(f["uninsured_at_interview"][in_cell], weights=weights[in_cell]).mean()
            )
        else:
            share = 0.0
        rates[int(value)] = share
        probability[cell == value] = share
    draw = _household_draw(household_id, seed)
    imputed_uninsured = unmeasured & ~other_public & (draw < probability)
    coverage[unmeasured] = np.select(
        [
            other_public[unmeasured],
            imputed_uninsured[unmeasured],
            f["medicaid_last_year"][unmeasured],
        ],
        [int(Coverage.OTHER), int(Coverage.UNINSURED), int(Coverage.MEDICAID_REPORTED)],
        default=int(Coverage.OTHER),
    )
    record = {
        "uninsured_rate_by_cell": {
            f"age band {value // 2}, Medicaid last year {bool(value % 2)}": rate
            for value, rate in sorted(rates.items())
        },
        "measured": measured,
        "imputed": unmeasured,
    }
    return coverage.astype(int), record


def summary_group(coverage: np.ndarray) -> np.ndarray:
    """Map coverage classes to the five reported groups (as their names)."""
    coverage = np.asarray(coverage)
    out = np.empty(coverage.shape, dtype=object)
    for name, members in SUMMARY_GROUPS.items():
        out[np.isin(coverage, [int(m) for m in members])] = name
    return out
