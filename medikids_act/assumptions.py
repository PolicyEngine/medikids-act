"""Stated assumptions: the reporting year, the bill's age limit, and cost growth.

Every figure here is an input read from a public source, with the source named
beside it. None is a result of this analysis.
"""

from __future__ import annotations

# The bill's new group starts two years after enactment. The 120th Congress
# convenes in January 2027, so 2029 is the earliest calendar year in which the
# group could be in force. Results are for that one year, with the bill treated
# as in force for all of it.
YEAR = 2029

# Section 1902(a)(10)(A)(i)(X) as the bill would add it: "individuals who have
# not attained 26 years of age".
AGE_LIMIT = 26

# CHIP defines a child as under 19 (SSA 2110(c)(1)); the engine's child
# Medicaid groups stop at 18 as well. The group-rate pricing uses the child
# rate below this age and an adult rate from it to 25.
CHILD_AGE_LIMIT = 19

# The date in the bill's new section 1905(ll): the 100 percent match applies
# only to people who would not have been eligible for full benefits under the
# State plan or waiver "as in effect on January 1, 2025".
LOOKBACK_DATE = "2025-01-01"

# The ACA adult group, SSA 1902(a)(10)(A)(i)(VIII), reaches 133 percent of the
# poverty line, 138 with the five-point income disregard. The expansion match
# applies only to people described in that group, so a person a state covered
# above this line under another authority draws the regular match.
ADULT_GROUP_INCOME_LIMIT = 1.38

# --- Growth in spending per enrollee -----------------------------------------
#
# The certified engine (policyengine-us 2.2.2) holds its Medicaid and CHIP
# calibration totals flat in nominal dollars after their data year. Each
# pricing below adds growth to 2029 from a named source.

# CMS Office of the Actuary, National Health Expenditure projections 2025-2034
# (tables released 2026), Table 17, spending per enrollee, calendar years:
# https://www.cms.gov/files/zip/nhe-projections-tables.zip
NHE_MEDICAID_PER_ENROLLEE = {2024: 11_050, 2029: 14_901}
NHE_CHIP_PER_ENROLLEE = {2024: 4_236, 2029: 5_784}

# MACPAC, MACStats: Medicaid and CHIP Data Book (February 2026), Exhibit 22,
# benefit spending per full-year-equivalent enrollee, fiscal 2023, all
# enrollees, federal plus state:
# https://www.macpac.gov/wp-content/uploads/2026/02/MACSTATS_Feb2026_WEB_508.pdf
MACPAC_FY2023_PER_FYE = {"child": 4_040, "other_adult": 5_757, "new_adult_group": 8_021}
MACPAC_BASE_FISCAL_YEAR = 2023

# CBO, Baseline Projections: Medicaid (February 2026), average federal spending
# on benefit payments per enrollee, fiscal years:
# https://www.cbo.gov/system/files/2026-02/51301-2026-02-medicaid.pdf
CBO_FEDERAL_PER_ENROLLEE = {
    "children": {2025: 2_710, 2029: 3_210},
    "traditional_adults": {2025: 4_820, 2029: 5_600},
}


def _annual_rate(series: dict[int, float]) -> float:
    (first_year, first), (last_year, last) = sorted(series.items())
    return (last / first) ** (1 / (last_year - first_year)) - 1


def model_allocation_growth() -> float:
    """Growth applied to the engine's state Medicaid spending totals.

    The engine divides fiscal 2023 state spending by enrollment calibrated to
    late 2024, which gives a per-enrollee level close to CMS's calendar 2024
    figure. The totals are therefore grown by CMS's projected growth in Medicaid
    spending per enrollee from calendar 2024 to 2029.
    """
    return NHE_MEDICAID_PER_ENROLLEE[YEAR] / NHE_MEDICAID_PER_ENROLLEE[2024]


def chip_growth() -> float:
    """Growth applied to the engine's fiscal 2024 separate-CHIP spending."""
    return NHE_CHIP_PER_ENROLLEE[YEAR] / NHE_CHIP_PER_ENROLLEE[2024]


def group_rate_growth(group: str) -> float:
    """Growth from fiscal 2023 to 2029 for a MACPAC per-enrollee rate.

    Compounds the average annual growth CBO projects for federal spending per
    enrollee in the matching category over fiscal 2025 to 2029.
    """
    series = CBO_FEDERAL_PER_ENROLLEE[
        {"child": "children", "other_adult": "traditional_adults"}[group]
    ]
    return (1 + _annual_rate(series)) ** (YEAR - MACPAC_BASE_FISCAL_YEAR)


# --- Population under 26 in the reporting year --------------------------------
#
# The engine ages a 2024 dataset to 2029 by scaling every household weight with
# total population growth, which overstates the number of young people: the
# Census Bureau projects the population under 26 to fall. Weights in the
# reporting year are therefore rescaled, by one factor for every household, so
# that the population under 26 matches the target below.
#
# Census Bureau, Vintage 2025 national estimates by single year of age,
# resident population under 26 on July 1, 2025:
# https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/national/asrh/nc-est2025-agesex-res.csv
CENSUS_UNDER_26_ESTIMATE_2025 = 108_865_174
# Census Bureau, 2023 National Population Projections, main series, resident
# population under 26:
# https://www2.census.gov/programs-surveys/popproj/datasets/2023/2023-popproj/np2023_d1_mid.csv
CENSUS_UNDER_26_PROJECTION = {2025: 106_956_880, 2029: 104_698_461}


def under_26_population_target() -> float:
    """The latest estimate carried to the reporting year at the projected rate of change."""
    projected_change = CENSUS_UNDER_26_PROJECTION[YEAR] / CENSUS_UNDER_26_PROJECTION[2025]
    return CENSUS_UNDER_26_ESTIMATE_2025 * projected_change


# Shares of people with employer coverage assumed to switch in the two partial
# cases. These are illustrations, not predictions.
EMPLOYER_SWITCH_SHARES = (0.25, 0.50)

# Seed for the household draw that picks which employer-covered households
# switch in the partial cases.
SWITCH_SEED = 5037

# Seed for the household draw that imputes who is uninsured on records without
# the survey's at-interview coverage items.
UNINSURED_SEED = 2029
