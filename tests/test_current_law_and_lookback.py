"""Household tests of the current-law conventions and the lookback run.

Expected values come from the bill text and current law, not from model
output.
"""

from __future__ import annotations

import pytest

from medikids_act import assumptions as A
from tests.conftest import Y
from tests.helpers import (
    COVERAGE_VARIABLES,
    FOSTER_YOUTH,
    STATE_FUNDED,
    fmap,
)


def test_new_fixture_households_are_what_they_claim(engine, lookback):
    category = engine.person("medicaid_category")
    then = lookback.person("medicaid_category")
    assert category["va_parent.parent"] == "ADULT" and then["va_parent.parent"] == "PARENT"
    assert category["dc_adult.adult"] == "NONE" and then["dc_adult.adult"] == "ADULT"
    assert lookback.person("medicaid_income_level")["dc_adult.adult"] > A.ADULT_GROUP_INCOME_LIMIT
    assert engine.person("is_basic_health_program_eligible")["dc_adult.adult"]


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
        if person not in (*STATE_FUNDED, FOSTER_YOUTH):
            assert ours[person] == pytest.approx(theirs[person])


def test_former_foster_youth_draw_the_regular_match(engine, current_law):
    # A title XIX group (SSA 1902(a)(10)(A)(i)(IX)) that the engine leaves at zero.
    assert engine.person("medicaid_enrolled")[FOSTER_YOUTH]
    assert engine.person("medicaid_federal_share")[FOSTER_YOUTH] == 0
    assert current_law.person("medicaid_federal_share")[FOSTER_YOUTH] == pytest.approx(
        fmap(current_law, "CA")
    )


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
