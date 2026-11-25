"""Outside figures the model's baseline is compared with.

Each entry is a published number with its source, year, unit and definition.
None is a result of this analysis. The comparison itself (model beside
benchmark) is written with the result tables, outside the repository.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Benchmark:
    key: str
    value: float
    unit: str
    year: str
    definition: str
    source: str


BENCHMARKS = (
    Benchmark(
        "population_under_26",
        109_372_451,
        "people",
        "July 1, 2024",
        "Resident population aged 0 to 25",
        "Census Bureau, Vintage 2025 national estimates by single year of age "
        "(nc-est2025-agesex-res.csv)",
    ),
    Benchmark(
        "population_under_19",
        76_996_761,
        "people",
        "July 1, 2024",
        "Resident population aged 0 to 18",
        "Census Bureau, Vintage 2025 national estimates by single year of age",
    ),
    Benchmark(
        "population_19_to_25",
        32_375_690,
        "people",
        "July 1, 2024",
        "Resident population aged 19 to 25",
        "Census Bureau, Vintage 2025 national estimates by single year of age",
    ),
    Benchmark(
        "medicaid_chip_child_enrollment",
        37_585_948,
        "people",
        "December 2024",
        "Children enrolled in Medicaid plus everyone enrolled in CHIP, 50 states and DC, "
        "point in time, comprehensive benefits; each state defines a child",
        "CMS, State Medicaid and CHIP Applications, Eligibility Determinations, and "
        "Enrollment Data, October 2026 release",
    ),
    Benchmark(
        "medicaid_chip_total_enrollment",
        79_154_413,
        "people",
        "December 2024",
        "Everyone enrolled in Medicaid or CHIP, all ages, 50 states and DC, point in time, "
        "comprehensive benefits",
        "CMS, State Medicaid and CHIP Applications, Eligibility Determinations, and "
        "Enrollment Data, October 2026 release",
    ),
    Benchmark(
        "chip_enrollment_total",
        7_326_747,
        "people",
        "December 2024",
        "Everyone enrolled in CHIP (separate and Medicaid-expansion), 50 states and DC, "
        "point in time",
        "CMS, State Medicaid and CHIP Applications, Eligibility Determinations, and "
        "Enrollment Data, October 2026 release",
    ),
    Benchmark(
        "separate_chip_ever_enrolled",
        3_330_000,
        "people",
        "fiscal 2024",
        "Children ever enrolled in a separate CHIP program during the year",
        "MACPAC, MACStats February 2026, Exhibit 32",
    ),
    Benchmark(
        "separate_chip_spending",
        8_394_400_000,
        "dollars",
        "fiscal 2024",
        "Benefit spending on separate CHIP programs and CHIP coverage of pregnant women, "
        "federal plus state",
        "MACPAC, MACStats February 2026, Exhibit 33",
    ),
    Benchmark(
        "medicaid_child_group_spending",
        132_600_000_000,
        "dollars",
        "fiscal 2023",
        "Medicaid benefit spending on the child eligibility group, federal plus state; "
        "excludes children eligible on the basis of disability and Medicaid-expansion CHIP",
        "MACPAC, MACStats February 2026, Exhibit 18",
    ),
    Benchmark(
        "medicaid_child_group_fye",
        32_816_000,
        "full-year-equivalent enrollees",
        "fiscal 2023",
        "Full-year-equivalent enrollment in the Medicaid child eligibility group",
        "MACPAC, MACStats February 2026, Exhibit 15",
    ),
    Benchmark(
        "cbo_children_federal_2029",
        95_000_000_000,
        "dollars",
        "fiscal 2029 (projected)",
        "Federal Medicaid benefit payments for the children category under current law",
        "CBO, Baseline Projections: Medicaid, February 2026",
    ),
    Benchmark(
        "cbo_children_enrollment_2029",
        30_000_000,
        "average monthly enrollees",
        "fiscal 2029 (projected)",
        "Average monthly Medicaid enrollment in the children category under current law",
        "CBO, Baseline Projections: Medicaid, February 2026",
    ),
    Benchmark(
        "nhe_medicaid_spending_2029",
        1_172_100_000_000,
        "dollars",
        "calendar 2029 (projected)",
        "Total Medicaid spending, federal plus state",
        "CMS Office of the Actuary, National Health Expenditure projections 2025-2034, Table 17",
    ),
    Benchmark(
        "nhe_medicaid_enrollment_2029",
        78_700_000,
        "people",
        "calendar 2029 (projected)",
        "Medicaid enrollment",
        "CMS Office of the Actuary, National Health Expenditure projections 2025-2034, Table 17",
    ),
    Benchmark(
        "uninsured_under_19",
        4_660_000,
        "people",
        "calendar 2024",
        "Children under 19 with no coverage for the entire year, civilian noninstitutionalized",
        "Census Bureau, Health Insurance Coverage in the United States: 2025 (P60-291), "
        "historical table HHI-02",
    ),
    Benchmark(
        "uninsured_19_to_25",
        4_530_000,
        "people",
        "calendar 2024",
        "People aged 19 to 25 with no coverage for the entire year, civilian noninstitutionalized",
        "Census Bureau, Health Insurance Coverage in the United States: 2025 (P60-291), "
        "historical table HHI-02",
    ),
    Benchmark(
        "employer_under_19",
        41_790_000,
        "people",
        "calendar 2024",
        "Children under 19 with employment-based coverage at any time in the year "
        "(coverage types overlap)",
        "Census Bureau, P60-291, historical table HHI-02",
    ),
    Benchmark(
        "employer_19_to_25",
        17_790_000,
        "people",
        "calendar 2024",
        "People aged 19 to 25 with employment-based coverage at any time in the year "
        "(coverage types overlap)",
        "Census Bureau, P60-291, historical table HHI-02",
    ),
    Benchmark(
        "marketplace_under_26",
        5_115_879,
        "people",
        "2026 open enrollment",
        "Marketplace plan selections by people under 26 at the end of open enrollment "
        "(not effectuated enrollment)",
        "CMS, 2026 Marketplace Open Enrollment Period State-Level Public Use File",
    ),
    Benchmark(
        "basic_health_program_under_26",
        313_549,
        "people",
        "2026 open enrollment",
        "Enrollment under 26 reported in the file's Basic Health Program fields: the Basic "
        "Health Programs of Minnesota, Oregon and DC, plus 289,860 in New York's Essential Plan "
        "Expansion, a section 1332 waiver program that is not a Basic Health Program but is "
        "reported in those fields (waiver ended July 1, 2026); a mixed comparator, so no ratio "
        "is meaningful",
        "CMS, 2026 Marketplace Open Enrollment Period State-Level Public Use File and its FAQs "
        "(What is a BHP Plan?)",
    ),
)

BY_KEY = {b.key: b for b in BENCHMARKS}
