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
    untouched = under_26 & np.isin(
        coverage,
        [int(COV.Coverage.OTHER), int(COV.Coverage.MEDICAID_REPORTED), int(COV.Coverage.MEDICAID)],
    )
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


flags = st.integers(min_value=1, max_value=40).flatmap(
    lambda n: st.fixed_dictionaries(
        {name: st.lists(st.booleans(), min_size=n, max_size=n) for name in COV.INPUTS}
    )
)


@given(flags)
@settings(max_examples=200, deadline=None)
def test_everyone_gets_exactly_one_class(sample):
    arrays = {name: np.array(values) for name, values in sample.items()}
    coverage = COV.classify(arrays)
    assert set(coverage.tolist()) <= {int(c) for c in COV.Coverage}
    groups = COV.summary_group(coverage)
    assert all(g in COV.SUMMARY_GROUPS for g in groups)
    # Each class sits in exactly one reported group.
    members = [int(m) for group in COV.SUMMARY_GROUPS.values() for m in group]
    assert sorted(members) == sorted(int(c) for c in COV.Coverage)


@given(flags)
@settings(max_examples=200, deadline=None)
def test_uninsured_means_no_coverage_of_any_kind(sample):
    arrays = {name: np.array(values) for name, values in sample.items()}
    coverage = COV.classify(arrays)
    any_coverage = np.zeros(coverage.shape, dtype=bool)
    for name in COV.INPUTS:
        any_coverage |= arrays[name]
    assert ((coverage == int(COV.Coverage.UNINSURED)) == ~any_coverage).all()
    # Modeled Medicaid enrollment always wins, because costs follow it.
    assert (coverage[arrays["medicaid_enrolled"]] == int(COV.Coverage.MEDICAID)).all()


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
