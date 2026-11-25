"""Household tests of the bill itself, on the certified engine version.

Expected values come from the bill text and current law, not from model
output: who is eligible, which match rate applies, and what must not change.
"""

from __future__ import annotations

import pytest

from medikids_act import assumptions as A
from tests.conftest import HOUSEHOLDS, Y
from tests.helpers import (
    EXPANSION,
    FULL,
    NONE,
    OLDER,
    REGULAR,
    UNDER_26,
    rate,
)


def test_everyone_under_26_is_eligible_and_nobody_older_gains(current_law, bill_nobody):
    eligible = bill_nobody.person("is_medicaid_eligible")
    assert all(eligible[p] for p in UNDER_26)
    before = current_law.person("is_medicaid_eligible")
    assert {p: eligible[p] for p in OLDER} == {p: before[p] for p in OLDER}


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
        ("tx_chip.child", FULL, FULL, FULL, FULL),
        ("tx_chip.young", FULL, FULL, FULL, FULL),
        ("tx_marketplace.child", FULL, FULL, FULL, FULL),
        ("tx_undocumented.child", FULL, NONE, FULL, FULL),
        ("ny_undocumented.child", FULL, NONE, FULL, FULL),
        # Inside the 2025 plan as a child: the state's regular match.
        ("ca_child.child", REGULAR, REGULAR, REGULAR, REGULAR),
        ("va_parent.child", REGULAR, REGULAR, REGULAR, REGULAR),
        # In the adult group: the expansion match, or the open readings.
        ("ca_adult.adult", EXPANSION, EXPANSION, FULL, REGULAR),
        ("ny_refugee.adult", EXPANSION, NONE, FULL, REGULAR),
        # In the adult group today although her 2025 group was the parent group:
        # the bill moves nobody between existing groups. The two adult-group
        # readings are mechanical overrides keyed to current membership, so she
        # draws 100 percent under adult_group_100 even though her 2025 group gave
        # full benefits; a historical-pathway version would keep the expansion match.
        ("va_parent.parent", EXPANSION, EXPANSION, FULL, REGULAR),
        # Inside the 2025 plan above the adult group's income limit: never the expansion match.
        ("dc_adult.adult", REGULAR, REGULAR, REGULAR, REGULAR),
        # Former foster youth: a title XIX group at the regular match.
        ("ca_foster.adult", REGULAR, REGULAR, REGULAR, REGULAR),
        # Wisconsin waiver adult: in the 2025 plan but not the ACA adult group, so
        # the regular match under every reading.
        ("wi_adult.adult", REGULAR, REGULAR, REGULAR, REGULAR),
    ],
)
def test_match_rates_under_each_reading(
    bill_everyone, person, primary, strict_v5, adult_100, adult_regular
):
    expected = {
        "medicaid_federal_share": primary,
        "medikids_federal_share_strict_v5": strict_v5,
        "medikids_federal_share_adult_group_100": adult_100,
        "medikids_federal_share_adult_group_regular": adult_regular,
    }
    for variable, kind in expected.items():
        assert bill_everyone.person(variable)[person] == pytest.approx(
            rate(bill_everyone, person, kind)
        ), (variable, kind)


def test_matched_enrollees_inside_the_2025_plan_keep_their_rate(current_law, bill_nobody):
    # The bill moves nobody between existing groups, so the floor must not
    # change the match of someone it does not touch.
    before = current_law.person("medicaid_federal_share")
    after = bill_nobody.person("medicaid_federal_share")
    for person in (
        "va_parent.parent",
        "va_parent.child",
        "ca_child.child",
        "ca_foster.adult",
        "wi_adult.adult",
    ):
        assert current_law.person("medicaid_enrolled")[person]
        assert before[person] > 0
        assert after[person] == pytest.approx(before[person])


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
