"""Household-level tests of the three reforms on the certified engine version.

Expected values come from the bill text and current law, not from model
output: who is eligible, which match rate applies, and what must not change.
"""

from __future__ import annotations

import pytest

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


def test_fixture_households_are_what_they_claim(engine):
    assert engine.person("is_chip_eligible")["tx_chip.child"]
    assert engine.person("pays_aca_premium")["tx_marketplace.child"]
    assert engine.tax_unit("aca_ptc")["tx_marketplace"] > 0
    assert engine.person("is_medicaid_ineligible_due_to_work_requirement")["ca_adult.adult"]
    assert not engine.person("is_medicaid_eligible")["tx_undocumented.child"]
    assert engine.person("medicaid_enrolled")["ny_undocumented.child"]
    assert engine.person("medicaid_enrolled")["ca_child.child"]
    assert engine.person("is_basic_health_program_eligible")["mn_bhp.adult"]
    assert not engine.person("is_medicaid_eligible")["tx_older.adult"]
    assert not engine.person("is_medicaid_eligible")["ny_refugee.adult"]


# --- Current-law conventions change nobody's coverage ------------------------


@pytest.mark.parametrize("variable", COVERAGE_VARIABLES)
def test_current_law_reform_leaves_coverage_alone(engine, current_law, variable):
    assert current_law.person(variable) == engine.person(variable)


def test_current_law_reform_leaves_the_premium_tax_credit_alone(engine, current_law):
    assert current_law.tax_unit("aca_ptc") == pytest.approx(engine.tax_unit("aca_ptc"))


STATE_FUNDED = ("ny_undocumented.parent", "ny_undocumented.child")


def test_state_funded_coverage_gets_no_federal_share(engine, current_law):
    # The engine gives the regular match; federal law pays nothing (42 U.S.C. 1396b(v)).
    for person in STATE_FUNDED:
        assert engine.person("medicaid_enrolled")[person]
        assert engine.person("medicaid_federal_share")[person] == pytest.approx(0.5)
        assert current_law.person("medicaid_federal_share")[person] == 0


def test_current_law_share_matches_the_engine_for_everyone_else(engine, current_law):
    ours, theirs = (
        current_law.person("medicaid_federal_share"),
        engine.person("medicaid_federal_share"),
    )
    for person in ours:
        if person not in STATE_FUNDED:
            assert ours[person] == pytest.approx(theirs[person])


def test_federal_immigration_test_uses_the_reporting_year_list(current_law):
    passes = current_law.person("medikids_federal_immigration_eligible")
    assert passes["ca_child.child"] and passes["tx_older.adult"]
    assert not passes["tx_undocumented.child"] and not passes["ny_undocumented.child"]
    # Refugees left the federal list in October 2026.
    assert not passes["ny_refugee.adult"]


def test_growth_is_applied_once(engine, current_law):
    # The engine applies a reform twice while it builds a system.
    instant = f"{Y}-01-01"
    before = (
        engine.sim.tax_benefit_system.parameters.calibration.gov.hhs.medicaid.totals.spending.TX(
            instant
        )
    )
    after = current_law.sim.tax_benefit_system.parameters.calibration.gov.hhs.medicaid.totals.spending.TX(
        instant
    )
    assert after == pytest.approx(before * A.model_allocation_growth())

    def chip(run):
        calibration = run.sim.tax_benefit_system.parameters.calibration
        return calibration.gov.hhs.cms.chip.spending.separate_chip.total.TX(instant)

    assert chip(current_law) == pytest.approx(chip(engine) * A.chip_growth())


# --- The lookback run ---------------------------------------------------------


def test_lookback_pins_eligibility_rules_but_not_the_poverty_line(engine, lookback):
    instant = f"{Y}-01-01"
    rules = lookback.sim.tax_benefit_system.parameters.gov.hhs.medicaid.eligibility
    current = engine.sim.tax_benefit_system.parameters
    assert "REFUGEE" in rules.eligible_immigration_statuses(instant)
    assert "REFUGEE" not in current.gov.hhs.medicaid.eligibility.eligible_immigration_statuses(
        instant
    )
    assert not rules.work_requirements.applies(instant)
    assert rules.categories.adult.income_limit.DC(instant) == pytest.approx(2.15)
    pinned_fpg = lookback.sim.tax_benefit_system.parameters.gov.hhs.fpg.first_person.CONTIGUOUS_US
    assert pinned_fpg(instant) == current.gov.hhs.fpg.first_person.CONTIGUOUS_US(instant)
    assert pinned_fpg(instant) > pinned_fpg(A.LOOKBACK_DATE)


@pytest.mark.parametrize(
    "person, expected",
    [
        ("ca_child.child", True),  # Medicaid child group
        ("ca_adult.adult", True),  # adult group; the work requirement postdates 2025
        ("ny_refugee.adult", True),  # refugees were on the 2025 list
        ("tx_chip.child", False),  # separate CHIP is a title XXI plan
        ("tx_chip.young", False),  # no group in a non-expansion state
        ("tx_marketplace.child", False),  # above every limit
        ("tx_undocumented.child", False),  # fails the federal immigration test
        ("ny_undocumented.child", False),  # state-funded coverage is not the title XIX plan
        ("tx_older.adult", False),
    ],
)
def test_lookback_eligibility(lookback, person, expected):
    assert lookback.person("medikids_lookback_title_xix_eligible")[person] is expected


# --- The bill with nobody choosing to enroll ---------------------------------


def test_everyone_under_26_is_eligible_and_nobody_older_gains(engine, bill_nobody):
    eligible = bill_nobody.person("is_medicaid_eligible")
    assert all(eligible[p] for p in UNDER_26)
    assert {p: eligible[p] for p in OLDER} == {
        p: engine.person("is_medicaid_eligible")[p] for p in OLDER
    }


def test_eligibility_alone_does_not_touch_the_premium_tax_credit(current_law, bill_nobody):
    # New 36B(c)(2)(D): eligibility through the new group is not minimum
    # essential coverage unless the person enrolls.
    assert bill_nobody.person("pays_aca_premium")["tx_marketplace.child"]
    assert bill_nobody.tax_unit("aca_ptc")["tx_marketplace"] == pytest.approx(
        current_law.tax_unit("aca_ptc")["tx_marketplace"]
    )
    assert bill_nobody.person("medicaid_enrolled")["tx_marketplace.child"] is False


def test_people_only_in_the_new_group_do_not_enroll_by_themselves(bill_nobody):
    # The dataset's stored take-up flag (default true) must not enroll them.
    enrolled = bill_nobody.person("medicaid_enrolled")
    for person in (
        "tx_chip.child",
        "tx_chip.young",
        "tx_undocumented.child",
        "tx_marketplace.child",
    ):
        assert enrolled[person] is False


def test_separate_chip_and_basic_health_program_end_under_26(bill_nobody):
    assert bill_nobody.person("is_chip_eligible")["tx_chip.child"] is False
    assert bill_nobody.person("is_basic_health_program_eligible")["mn_bhp.adult"] is False


def test_community_engagement_exception_restores_the_adult_group(bill_nobody):
    assert (
        bill_nobody.person("is_medicaid_ineligible_due_to_work_requirement")["ca_adult.adult"]
        is False
    )
    assert bill_nobody.person("medikids_existing_group_eligible")["ca_adult.adult"]
    assert bill_nobody.person("medicaid_enrolled")["ca_adult.adult"]
    assert bill_nobody.person("medicaid_federal_share")["ca_adult.adult"] == pytest.approx(0.9)


def test_existing_enrollees_keep_coverage_and_their_match(current_law, bill_nobody):
    assert bill_nobody.person("medicaid_enrolled")["ca_child.child"]
    assert bill_nobody.person("medicaid_federal_share")["ca_child.child"] == pytest.approx(
        current_law.person("medicaid_federal_share")["ca_child.child"]
    )


def test_state_funded_coverage_moves_to_the_full_federal_match(bill_nobody):
    assert bill_nobody.person("medicaid_enrolled")["ny_undocumented.child"]
    assert bill_nobody.person("medicaid_federal_share")["ny_undocumented.child"] == pytest.approx(
        1.0
    )


# --- The bill with everyone under 26 enrolling -------------------------------


def test_everyone_under_26_can_enroll_and_nobody_older_is_added(current_law, bill_everyone):
    enrolled = bill_everyone.person("medicaid_enrolled")
    assert all(enrolled[p] for p in UNDER_26)
    assert {p: enrolled[p] for p in OLDER} == {
        p: current_law.person("medicaid_enrolled")[p] for p in OLDER
    }


def test_enrolling_takes_a_child_out_of_the_marketplace(current_law, bill_everyone):
    assert bill_everyone.person("pays_aca_premium")["tx_marketplace.child"] is False
    assert (
        bill_everyone.tax_unit("aca_ptc")["tx_marketplace"]
        <= current_law.tax_unit("aca_ptc")["tx_marketplace"]
    )


@pytest.mark.parametrize(
    "person, primary, strict_v5, adult_100, adult_regular",
    [
        # Outside the 2025 plan: 100 percent, unless (v)(5) bars payment.
        ("tx_chip.child", 1.0, 1.0, 1.0, 1.0),
        ("tx_chip.young", 1.0, 1.0, 1.0, 1.0),
        ("tx_marketplace.child", 1.0, 1.0, 1.0, 1.0),
        ("tx_undocumented.child", 1.0, 0.0, 1.0, 1.0),
        ("ny_undocumented.child", 1.0, 0.0, 1.0, 1.0),
        # Inside the 2025 plan as a child: the state's regular match (California: 50 percent).
        ("ca_child.child", 0.5, 0.5, 0.5, 0.5),
        # Inside the 2025 plan in the adult group: the expansion match, or the open readings.
        ("ca_adult.adult", 0.9, 0.9, 1.0, 0.5),
        ("ny_refugee.adult", 0.9, 0.0, 1.0, 0.5),
    ],
)
def test_match_rates_under_each_reading(
    bill_everyone, person, primary, strict_v5, adult_100, adult_regular
):
    assert bill_everyone.person("medicaid_federal_share")[person] == pytest.approx(primary)
    assert bill_everyone.person("medikids_federal_share_strict_v5")[person] == pytest.approx(
        strict_v5
    )
    assert bill_everyone.person("medikids_federal_share_adult_group_100")[person] == pytest.approx(
        adult_100
    )
    assert bill_everyone.person("medikids_federal_share_adult_group_regular")[
        person
    ] == pytest.approx(adult_regular)


def test_people_26_and_over_keep_their_match(current_law, bill_everyone):
    ours, before = (
        bill_everyone.person("medicaid_federal_share"),
        current_law.person("medicaid_federal_share"),
    )
    for person in OLDER:
        assert ours[person] == pytest.approx(before[person])


def test_federal_plus_state_equals_total(bill_everyone):
    cost = bill_everyone.person("medicaid_cost")
    federal = bill_everyone.person("medicaid_federal_cost")
    state = bill_everyone.person("medicaid_state_cost")
    for person in cost:
        assert federal[person] + state[person] == pytest.approx(cost[person], rel=1e-5, abs=0.01)
        assert 0 <= federal[person] <= cost[person] * (1 + 1e-6) + 0.01


def test_cost_of_people_enrolled_before_and_after_is_unchanged(current_law, bill_everyone):
    assert bill_everyone.person("medicaid_cost")["ca_child.child"] == pytest.approx(
        current_law.person("medicaid_cost")["ca_child.child"], rel=1e-5
    )


def test_group_rate_by_age(bill_everyone):
    rate = bill_everyone.person("medikids_group_rate")
    adult_rate = A.MACPAC_FY2023_PER_FYE["other_adult"] * A.group_rate_growth("other_adult")
    for name, (_, members) in HOUSEHOLDS.items():
        for person, age, _, _ in members:
            value = rate[f"{name}.{person}"]
            if age >= A.AGE_LIMIT:
                assert value == 0
            elif age >= A.CHILD_AGE_LIMIT:
                assert value == pytest.approx(adult_rate, rel=1e-5)
            else:
                assert value > 0
    # Texas's child rate is above California's in the engine's MACPAC parameters.
    assert rate["tx_chip.child"] > rate["ca_child.child"]


def test_group_rate_cost_only_for_enrollees(bill_nobody, bill_everyone):
    assert bill_nobody.person("medikids_group_rate_cost")["tx_chip.child"] == 0
    assert bill_everyone.person("medikids_group_rate_cost")["tx_chip.child"] == pytest.approx(
        bill_everyone.person("medikids_group_rate")["tx_chip.child"]
    )


def test_bill_does_not_reach_other_years(bill_everyone):
    # Prior-year lookups inside the engine must see current law.
    eligible = bill_everyone.person("is_medicaid_eligible", Y - 1)
    assert eligible["tx_chip.young"] is False
