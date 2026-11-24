"""Property tests of the switching cases and the coverage classification."""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from medikids_act import assumptions as A
from medikids_act import cases as C
from medikids_act import coverage as COV

population = st.integers(min_value=1, max_value=60).flatmap(
    lambda n: st.tuples(
        st.lists(st.integers(0, 90), min_size=n, max_size=n),
        st.lists(st.sampled_from([int(c) for c in COV.Coverage]), min_size=n, max_size=n),
        st.lists(st.integers(1, 12), min_size=n, max_size=n),
        st.integers(0, 2**31 - 1),
    )
)


def _sets(age, coverage, household, seed):
    age, coverage, household = np.array(age), np.array(coverage), np.array(household)
    return (
        age,
        coverage,
        {
            case: C.case_enrolls(
                case, age=age, coverage=coverage, household_id=household, seed=seed
            )
            for case in C.CASES
        },
    )


@given(population)
@settings(max_examples=200, deadline=None)
def test_chain_is_nested_and_stays_under_26(sample):
    age, _coverage, sets = _sets(*sample)
    for earlier, later in zip(C.CHAIN, C.CHAIN[1:], strict=False):
        assert not (sets[earlier] & ~sets[later]).any(), (earlier, later)
    for case, enrolls in sets.items():
        assert not enrolls[age >= A.AGE_LIMIT].any(), case


@given(population)
@settings(max_examples=200, deadline=None)
def test_every_case_contains_the_forced_moves(sample):
    age, coverage, sets = _sets(*sample)
    forced = C.transfers(age, coverage)
    assert (sets["floor"] == forced).all()
    for case, enrolls in sets.items():
        assert enrolls[forced].all(), case


@given(population)
@settings(max_examples=200, deadline=None)
def test_named_cases_mean_what_they_say(sample):
    age, coverage, sets = _sets(*sample)
    under_26 = age < A.AGE_LIMIT
    assert (sets["everyone"] == under_26).all()
    assert not (sets["newborns"] & ~sets["everyone"]).any()
    assert not (sets["uninsured"] & ~sets["uninsured_wide"]).any()
    reported = under_26 & (coverage == int(COV.Coverage.MEDICAID_REPORTED))
    assert sets["uninsured_wide"][reported].all()
    assert not sets["uninsured"][reported].any()
    assert sets["newborns"][age < 1].all()
    uninsured = under_26 & (coverage == int(COV.Coverage.UNINSURED))
    assert sets["uninsured"][uninsured].all()
    marketplace = under_26 & (coverage == int(COV.Coverage.MARKETPLACE))
    assert sets["marketplace"][marketplace].all()
    assert not sets["uninsured"][marketplace].any()
    employer = under_26 & (coverage == int(COV.Coverage.EMPLOYER))
    assert not sets["marketplace"][employer].any()
    # No case below "everyone" enrolls people who hold other coverage or who
    # report Medicaid.
    untouched = under_26 & np.isin(coverage, [int(COV.Coverage.OTHER), int(COV.Coverage.MEDICAID)])
    for case in ("floor", "newborns", "uninsured", "marketplace", "employer_25", "employer_50"):
        assert not sets[case][untouched & (age >= 1)].any(), case


@given(st.lists(st.integers(1, 40), min_size=1, max_size=80), st.integers(0, 2**31 - 1))
@settings(max_examples=200, deadline=None)
def test_household_draw_is_shared_within_a_household_and_reproducible(household, seed):
    household = np.array(household)
    draw = C.household_draw(household, seed)
    assert ((draw >= 0) & (draw < 1)).all()
    for value in np.unique(household):
        assert np.unique(draw[household == value]).size == 1
    assert (draw == C.household_draw(household, seed)).all()


people = st.integers(min_value=1, max_value=40).flatmap(
    lambda n: st.tuples(
        st.fixed_dictionaries(
            {name: st.lists(st.booleans(), min_size=n, max_size=n) for name in COV.INPUTS}
        ),
        st.lists(st.integers(0, 90), min_size=n, max_size=n),
        st.lists(st.floats(0.1, 5000), min_size=n, max_size=n),
        st.lists(st.integers(1, 12), min_size=n, max_size=n),
        st.integers(0, 2**31 - 1),
    )
)


def _classify(sample):
    raw, age, weights, household, seed = sample
    arrays = {name: np.array(values) for name, values in raw.items()}
    # The survey cannot say "uninsured" where it did not ask.
    arrays["uninsured_at_interview"] &= arrays["interview_items_present"]
    coverage, record = COV.classify(
        arrays,
        age=np.array(age),
        weights=np.array(weights),
        household_id=np.array(household),
        seed=seed,
    )
    return arrays, coverage, record


@given(people)
@settings(max_examples=200, deadline=None)
def test_everyone_gets_exactly_one_class(sample):
    _arrays, coverage, record = _classify(sample)
    assert set(coverage.tolist()) <= {int(c) for c in COV.Coverage}
    assert all(g in COV.SUMMARY_GROUPS for g in COV.summary_group(coverage))
    # Each class sits in exactly one reported group.
    members = [int(m) for group in COV.SUMMARY_GROUPS.values() for m in group]
    assert sorted(members) == sorted(int(c) for c in COV.Coverage)
    assert not (record["measured"] & record["imputed"]).any()


@given(people)
@settings(max_examples=200, deadline=None)
def test_modeled_enrollment_and_private_coverage_come_first(sample):
    arrays, coverage, _record = _classify(sample)
    medicaid = arrays["medicaid_enrolled"]
    assert (coverage[medicaid] == int(COV.Coverage.MEDICAID)).all()
    chip = arrays["chip_enrolled"] & ~medicaid
    assert (coverage[chip] == int(COV.Coverage.CHIP)).all()
    public = medicaid | arrays["chip_enrolled"] | arrays["basic_health_program_enrolled"]
    employer = arrays["has_esi"] & ~public
    assert (coverage[employer] == int(COV.Coverage.EMPLOYER)).all()
    # Nobody with modeled enrollment, employer or Marketplace coverage is uninsured.
    covered = public | arrays["has_esi"] | arrays["person_receives_aca"]
    covered |= arrays["has_marketplace_health_coverage_at_interview"]
    assert not (coverage[covered] == int(COV.Coverage.UNINSURED)).any()


@given(people)
@settings(max_examples=200, deadline=None)
def test_where_the_survey_asked_its_answer_decides(sample):
    arrays, coverage, record = _classify(sample)
    measured = record["measured"]
    uninsured = coverage == int(COV.Coverage.UNINSURED)
    assert (uninsured[measured] == arrays["uninsured_at_interview"][measured]).all()
    # Measured and imputed people are exactly the ones the first step left over.
    left_over = ~(
        arrays["medicaid_enrolled"]
        | arrays["chip_enrolled"]
        | arrays["basic_health_program_enrolled"]
        | arrays["has_esi"]
        | arrays["person_receives_aca"]
        | arrays["has_marketplace_health_coverage_at_interview"]
    )
    assert ((measured | record["imputed"]) == left_over).all()
    assert (measured == (left_over & arrays["interview_items_present"])).all()


@given(people)
@settings(max_examples=200, deadline=None)
def test_imputation_never_marks_people_with_other_public_coverage(sample):
    arrays, coverage, record = _classify(sample)
    imputed = record["imputed"]
    uninsured = coverage == int(COV.Coverage.UNINSURED)
    other_public = arrays["medicare_enrolled"] | arrays["other_public_last_year"]
    assert not (uninsured & imputed & other_public).any()
    # A cell with nobody measured as uninsured imputes nobody as uninsured.
    if not arrays["uninsured_at_interview"].any():
        assert not (uninsured & imputed).any()


def test_imputed_share_matches_the_measured_share():
    # Two age bands with different measured rates; a large unmeasured group in
    # each must come out near its own band's rate.
    rng = np.random.default_rng(0)
    n = 40_000
    age = np.where(rng.random(n) < 0.5, 10, 22)
    present = rng.random(n) < 0.4
    rate = np.where(age < 19, 0.3, 0.7)
    uninsured = present & (rng.random(n) < rate)
    arrays = {name: np.zeros(n, dtype=bool) for name in COV.INPUTS}
    arrays["interview_items_present"] = present
    arrays["uninsured_at_interview"] = uninsured
    coverage, record = COV.classify(
        arrays, age=age, weights=np.ones(n), household_id=np.arange(n), seed=1
    )
    imputed = record["imputed"]
    assert imputed.sum() > 10_000
    is_uninsured = coverage == int(COV.Coverage.UNINSURED)
    for band, expected in ((age < 19, 0.3), (age >= 19, 0.7)):
        share = is_uninsured[imputed & band].mean()
        assert abs(share - expected) < 0.02, (share, expected)
    # People with Medicaid in the prior year form their own cell.
    arrays["medicaid_last_year"] = np.ones(n, dtype=bool)
    arrays["uninsured_at_interview"] = np.zeros(n, dtype=bool)
    coverage, record = COV.classify(
        arrays, age=age, weights=np.ones(n), household_id=np.arange(n), seed=1
    )
    assert (coverage[record["imputed"]] == int(COV.Coverage.MEDICAID_REPORTED)).all()


def test_survey_inputs_decode_the_survey_codes():
    columns = {
        "NOW_COV": np.array([1.0, 2.0, np.nan]),
        "CAID": np.array([1, 2, 0]),
        "MCARE": np.array([2, 2, 1]),
        "MIL": np.array([2, 1, 2]),
        "CHAMPVA": np.array([2, 2, 2]),
    }
    out = COV.survey_inputs(columns)
    assert out["interview_items_present"].tolist() == [True, True, False]
    assert out["uninsured_at_interview"].tolist() == [False, True, False]
    assert out["medicaid_last_year"].tolist() == [True, False, False]
    assert out["other_public_last_year"].tolist() == [False, True, True]


def test_growth_factors_are_above_one_and_from_the_stated_sources():
    assert (
        A.model_allocation_growth()
        == A.NHE_MEDICAID_PER_ENROLLEE[2029] / A.NHE_MEDICAID_PER_ENROLLEE[2024]
    )
    assert A.chip_growth() > 1
    assert 1 < A.group_rate_growth("child") < 2
    assert 1 < A.group_rate_growth("other_adult") < 2
    target = A.under_26_population_target()
    assert A.CENSUS_UNDER_26_PROJECTION[2029] < target < A.CENSUS_UNDER_26_ESTIMATE_2025
