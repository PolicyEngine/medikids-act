"""The MediKids Act as PolicyEngine reforms, written against policyengine-us 2.2.2.

Three reforms are built here. Each one is passed to
``policyengine.us.managed_microsimulation(reform=...)`` or, in tests, to
``policyengine_us.Simulation``.

``current_law_reform``
    Current law with this analysis's cost conventions: spending totals grown to
    the reporting year, a federal share of zero for state-funded coverage, and
    the group-rate pricing variables. It changes nobody's eligibility,
    enrollment, premium tax credit or CHIP status.

``medikids_reform``
    The bill on top of ``current_law_reform``: the under-26 group, the
    enroll-only rule for the premium tax credit, the exemption from community
    engagement requirements, and the bill's two match rates.

``lookback_reform``
    Medicaid and CHIP eligibility rules pinned to their values on 2025-01-01,
    applied to the reporting year's population. Its outputs feed the two
    reforms above as inputs: who would have been eligible under the State plan
    as in effect on that date (the bill's test for the 100 percent match), and
    each state's enrollment under those rules (the base for per-enrollee
    prices).

Every departure from the engine is a variable or parameter change in this
file. Engine formulas are reused, not copied, wherever one exists.
"""

from __future__ import annotations

import numpy as np
from policyengine_core.parameters import Parameter
from policyengine_core.periods import instant
from policyengine_core.reforms import Reform
from policyengine_us.model_api import *
from policyengine_us.variables.gov.hhs.medicaid.costs.medicaid_group import MedicaidGroup
from policyengine_us.variables.gov.hhs.medicaid.costs.per_capita_cost_helpers import (
    calculate_per_capita_cost,
)
from policyengine_us.variables.gov.hhs.medicaid.eligibility.is_medicaid_eligible import (
    is_medicaid_eligible as _engine_is_medicaid_eligible,
)

from medikids_act import assumptions as A

# The engine's model_api exports YEAR (the definition period), so the reporting
# year gets its own name here.
REPORTING_YEAR = A.YEAR
_START = instant(f"{REPORTING_YEAR}-01-01")
_STOP = instant(f"{REPORTING_YEAR}-12-31")

# Parameter subtrees that hold Medicaid and CHIP eligibility rules. The lookback
# reform pins every parameter under them to its value on 2025-01-01. The state
# folders are the ones the engine's Medicaid and CHIP eligibility formulas read.
LOOKBACK_SUBTREES = (
    "gov.hhs.medicaid.eligibility",
    "gov.hhs.chip",
    "gov.states.ar.dhs.medicaid",
    "gov.states.ca.chhs",
    "gov.states.ca.dhcs",
    "gov.states.il.hfs",
    "gov.states.mo.dss",
    "gov.states.ms.dom",
    "gov.states.va.dmas",
)


# --- Variables shared by every run -------------------------------------------


class medikids_under_26(Variable):
    value_type = bool
    entity = Person
    definition_period = YEAR
    label = "Under 26 in a year the MediKids group is priced"
    documentation = (
        "The bill's new group, SSA 1902(a)(10)(A)(i)(X): individuals who have not "
        "attained 26 years of age. True only in the reporting year, so that prior-year "
        "lookups inside the engine see current law."
    )
    reference = "https://www.congress.gov/bill/119th-congress/senate-bill/5037"

    def formula(person, period, parameters):
        in_reporting_year = period.start.year == REPORTING_YEAR
        return (person("age", period) < A.AGE_LIMIT) & in_reporting_year


class medikids_federal_immigration_eligible(Variable):
    value_type = bool
    entity = Person
    definition_period = YEAR
    label = "Meets the federal Medicaid immigration test"
    documentation = (
        "The federal part of the engine's Medicaid immigration test: citizens, and people "
        "in an eligible status who are exempt from or past the five-year bar. It leaves "
        "out the state-funded routes that the engine's "
        "is_medicaid_immigration_status_eligible adds (states that cover undocumented "
        "people, and California's rule), because federal matching funds do not pay for "
        "those. The dataset carries no years-since-entry input, so the engine's default "
        "(five years) treats every lawful permanent resident as past the bar."
    )
    reference = (
        "https://www.law.cornell.edu/uscode/text/42/1396b#v",
        "https://www.law.cornell.edu/uscode/text/8/1613",
    )

    def formula(person, period, parameters):
        p = parameters(period).gov.hhs.medicaid.eligibility
        status = person("immigration_status", period)
        status_str = status.decode_to_str()
        citizen = status == status.possible_values.CITIZEN
        eligible_status = np.isin(status_str, p.eligible_immigration_statuses)
        bar_exempt = np.isin(status_str, p.bar_exempt_immigration_statuses)
        past_bar = person("years_since_us_entry", period.this_year) >= p.five_year_bar_years
        return citizen | (eligible_status & (bar_exempt | past_bar))


class medikids_existing_group_eligible(Variable):
    value_type = bool
    entity = Person
    definition_period = YEAR
    label = "Eligible for Medicaid through a group that exists under current law"
    documentation = (
        "The engine's own is_medicaid_eligible formula, kept under a new name so that the "
        "bill's under-26 group can be added beside it. The premium tax credit gate reads "
        "this variable: under the bill's new 36B(c)(2)(D), eligibility through the "
        "under-26 group alone does not block the credit."
    )
    reference = "https://www.law.cornell.edu/uscode/text/42/1396a#a_10"

    formula = _engine_is_medicaid_eligible.formula


class medikids_lookback_eligible(Variable):
    value_type = bool
    entity = Person
    definition_period = YEAR
    default_value = False
    label = "Would have been eligible under the title XIX State plan as in effect on 2025-01-01"
    documentation = (
        "Input, computed in the lookback run. People for whom this is false draw the "
        "bill's 100 percent match (new SSA 1905(ll))."
    )


class medikids_lookback_adult_group(Variable):
    value_type = bool
    entity = Person
    definition_period = YEAR
    default_value = False
    label = "In the ACA adult group under the rules in effect on 2025-01-01"
    documentation = "Input, computed in the lookback run. These people keep the expansion match."


class medikids_in_aca_adult_group(Variable):
    value_type = bool
    entity = Person
    definition_period = YEAR
    label = "In the ACA adult group (SSA 1902(a)(10)(A)(i)(VIII))"
    documentation = (
        "The engine's ADULT Medicaid category where it is the ACA adult group, the group "
        "SSA 1905(y) matches at the expansion rate. Wisconsin covers adults below the "
        "poverty line through a section 1115 waiver, which the engine also puts in its "
        "ADULT category (income limit 100 percent of the poverty line); those adults are "
        "matched at the state's regular rate. A state whose adult income limit is below "
        "the ACA group's 138 percent is therefore treated as covering adults by waiver. The "
        "variable applies no income cap of its own: in the reporting year no state's adult "
        "limit exceeds 138 percent (a check confirms it), and the lookback caps the group at "
        "138 percent in lookback_inputs, because DC's 2025 limit was higher."
    )
    reference = (
        "https://www.law.cornell.edu/uscode/text/42/1396d#y",
        (
            "https://www.medicaid.gov/medicaid/section-1115-demonstrations/downloads/"
            "wi-badgercare-reform-dmnstn-aprvl-evltn-dsgn-01022026.pdf"
        ),
    )

    def formula(person, period, parameters):
        category = person("medicaid_category", period)
        state = person.household("state_code", period)
        limits = parameters(period).gov.hhs.medicaid.eligibility.categories.adult.income_limit
        aca_state = limits[state] >= A.ADULT_GROUP_INCOME_LIMIT - 1e-9
        return (category == category.possible_values.ADULT) & aca_state


class medikids_case_enrolls(Variable):
    value_type = bool
    entity = Person
    definition_period = YEAR
    default_value = False
    label = "Enrolls in Medicaid in this switching case"
    documentation = (
        "Input, set for each switching case. It decides enrollment for people who are "
        "eligible only through the under-26 group, and adds enrollment for previously "
        "eligible people the case moves in. The dataset's stored take-up flag is not "
        "used for people eligible only through the new group."
    )


def _regular_fmap(person, period, parameters):
    state = person.household("state_code", period)
    return parameters(period).gov.hhs.medicaid.cost_share.fmap[state]


def _matched_under_current_law(person, period):
    """Whether federal matching funds pay for this person under current law.

    A Medicaid category, or California's former foster youth group (a title XIX
    group that the engine keeps outside its categories), together with the
    federal immigration test.
    """
    category = person("medicaid_category", period)
    in_group = (category != category.possible_values.NONE) | person("ca_ffyp_eligible", period)
    return in_group & person("medikids_federal_immigration_eligible", period)


def _current_law_share(person, period, parameters):
    """Federal share under current law, with state-funded coverage at zero.

    The engine (2.2.2) gives the regular match to every enrollee with a
    Medicaid category, including people who pass the immigration test only
    through a state-funded route. Federal law pays nothing for them
    (42 U.S.C. 1396b(v)), so this sets their share to zero, as later
    policyengine-us versions do. It also gives the regular match to former
    foster youth, whom the engine leaves at zero, and the regular match to
    Wisconsin's waiver adults, to whom the engine gives the expansion match
    (see ``medikids_in_aca_adult_group``).
    """
    matched = _matched_under_current_law(person, period)
    expansion_fmap = parameters(period).gov.hhs.medicaid.cost_share.expansion_fmap
    return select(
        [~matched, person("medikids_in_aca_adult_group", period)],
        [0, expansion_fmap],
        default=_regular_fmap(person, period, parameters),
    )


# Readings of the bill's match rates. The first is the one the estimate leads
# with; the others answer points the bill's text leaves open.
#
# primary
#     People under 26 who would not have been eligible under the State plan as
#     in effect on 2025-01-01 draw 100 percent (new SSA 1905(ll)). Everyone
#     else under 26 draws what current law gives them: the rate of their
#     current group if they have one, otherwise the rate of the group they
#     would have been in under the 2025 rules (the expansion rate for the ACA
#     adult group, the state's regular rate otherwise).
# strict_v5
#     The bill does not amend SSA 1903(v)(5), which from October 2026 bars
#     federal payment for anyone but citizens, lawful permanent residents,
#     Cuban and Haitian entrants and Compact of Free Association residents. On
#     the strict reading States must cover everyone else under 26 with no
#     federal payment. The engine cannot apply that paragraph's exceptions
#     (emergency care, and the State option for lawfully residing children),
#     so this reading overstates the loss of federal payment.
# adult_group_100
#     The 1905(ll) test names "full benefits" only. If the ACA adult group's
#     benchmark coverage does not count as full benefits, its members aged 19
#     to 25 draw 100 percent. As implemented this is a mechanical rate
#     override: it keys on the adult-group flag used below (current membership
#     for a person matched today, the 2025 group otherwise) and does not test
#     whether the person had another full-benefit pathway under the 2025 rules.
#     A person in the adult group today whose 2025 group gave full benefits
#     (the Virginia parent fixture) gets 100 percent here although that reading
#     of the bill would keep her current rate. The engine assigns one category
#     per person, so overlaps between the adult group and other groups cannot
#     be seen.
# adult_group_regular
#     If States must enroll those members under the new group instead of the
#     adult group, the expansion rate no longer reaches them and they draw the
#     state's regular rate. It uses the same adult-group flag, with the same
#     limit.
READINGS = ("primary", "strict_v5", "adult_group_100", "adult_group_regular")


def _bill_share(person, period, parameters, reading="primary"):
    """Federal share under the bill, for one reading of its match rates."""
    current = _current_law_share(person, period, parameters)
    regular = _regular_fmap(person, period, parameters)
    expansion_fmap = parameters(period).gov.hhs.medicaid.cost_share.expansion_fmap
    inside_2025_plan = person("medikids_lookback_eligible", period)
    # A person with a matched group today keeps that group's rate: the bill
    # does not move anyone between existing groups. The 2025 group matters only
    # for people current law has since cut off.
    matched_now = _matched_under_current_law(person, period)
    in_adult_group = where(
        matched_now,
        person("medikids_in_aca_adult_group", period),
        person("medikids_lookback_adult_group", period),
    )
    rate = where(matched_now, current, where(in_adult_group, expansion_fmap, regular))
    if reading == "adult_group_100":
        rate = where(in_adult_group, 1.0, rate)
    elif reading == "adult_group_regular":
        rate = where(in_adult_group, regular, rate)
    under_bill = where(inside_2025_plan, rate, 1.0)
    if reading == "strict_v5":
        paid = person("medikids_federal_immigration_eligible", period)
        under_bill = where(paid, under_bill, 0)
    return where(person("medikids_under_26", period), under_bill, current)


def _share_variable(name: str, reading: str) -> type:
    """A federal-share variable: ``current_law``, or one reading of the bill.

    The formula is set on the class itself. A subclass that only inherits a
    formula would be treated by the engine as having none, and the variable it
    replaces would keep its old formula.
    """

    def formula(person, period, parameters):
        if reading == "current_law":
            return _current_law_share(person, period, parameters)
        return _bill_share(person, period, parameters, reading)

    return type(
        name,
        (Variable,),
        {
            "value_type": float,
            "entity": Person,
            "label": f"Medicaid federal share ({reading})",
            "unit": "/1",
            "definition_period": YEAR,
            "reference": "https://www.law.cornell.edu/uscode/text/42/1396d",
            "defined_for": "medicaid_enrolled",
            "formula": formula,
        },
    )


def _federal_cost_variable(name: str, cost: str, share: str) -> type:
    """Federal cost: a cost variable times a federal-share variable."""

    def formula(person, period, parameters):
        return person(cost, period) * person(share, period)

    return type(
        name,
        (Variable,),
        {
            "value_type": float,
            "entity": Person,
            "label": f"Federal part of {cost} at {share}",
            "unit": USD,
            "definition_period": YEAR,
            "defined_for": "medicaid_enrolled",
            "formula": formula,
        },
    )


def alternative_reading_variables() -> list[type]:
    """Share and federal-cost variables for the readings other than the primary one."""
    variables = []
    for reading in READINGS[1:]:
        share = f"medikids_federal_share_{reading}"
        variables.append(_share_variable(share, reading))
        variables.append(
            _federal_cost_variable(
                f"medikids_medicaid_federal_cost_{reading}", "medicaid_cost", share
            )
        )
        variables.append(
            _federal_cost_variable(
                f"medikids_group_rate_federal_cost_{reading}", "medikids_group_rate_cost", share
            )
        )
    return variables


def _state_values(node) -> dict[str, float]:
    """Values of a by-state parameter node at an instant, keyed by state code."""
    out = {}
    for state in StateCode:
        try:
            out[state.name] = float(getattr(node, state.name))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return out


class medikids_group_rate(Variable):
    value_type = float
    entity = Person
    unit = USD
    definition_period = YEAR
    label = "Medicaid cost per enrollee at MACPAC group rates"
    documentation = (
        "The second pricing. Under 19: the state's child-group rate from the engine's "
        "parameters (MACPAC benefit spending divided by enrollment), rescaled so that the "
        "national average equals MACPAC's fiscal 2023 child spending per full-year-"
        "equivalent enrollee. Ages 19 to 25: MACPAC's fiscal 2023 national rate for the "
        "'other adult' group, all enrollees. That is a choice, not the engine's grouping: "
        "the engine puts ACA adult-group members in its expansion-adult group. Both are "
        "grown to the reporting year. Zero at 26 and over."
    )
    reference = "https://www.macpac.gov/wp-content/uploads/2026/02/MACSTATS_Feb2026_WEB_508.pdf"

    def formula(person, period, parameters):
        age = person("age", period)
        child_group = np.full(person.count, MedicaidGroup.CHILD)
        state_child_rate = calculate_per_capita_cost(
            person, period, parameters, child_group, MedicaidGroup, groups=[MedicaidGroup.CHILD]
        )
        p = parameters(period).calibration.gov.hhs.medicaid
        spending = _state_values(p.spending.by_eligibility_group.child)
        enrollment = _state_values(p.enrollment.child)
        national_rate = sum(spending.values()) / sum(enrollment[s] for s in spending)
        child_rate = (
            state_child_rate
            * (A.MACPAC_FY2023_PER_FYE["child"] / national_rate)
            * A.group_rate_growth("child")
        )
        adult_rate = A.MACPAC_FY2023_PER_FYE["other_adult"] * A.group_rate_growth("other_adult")
        rate = where(age < A.CHILD_AGE_LIMIT, child_rate, adult_rate)
        return where(age < A.AGE_LIMIT, rate, 0)


class medikids_group_rate_cost(Variable):
    value_type = float
    entity = Person
    unit = USD
    definition_period = YEAR
    label = "Medicaid cost of enrollees under 26 at MACPAC group rates"
    defined_for = "medicaid_enrolled"
    adds = ["medikids_group_rate"]  # noqa: RUF012 (the engine expects a list here)


class medikids_group_rate_federal_cost(Variable):
    value_type = float
    entity = Person
    unit = USD
    definition_period = YEAR
    label = "Federal share of the group-rate Medicaid cost"
    defined_for = "medicaid_enrolled"

    def formula(person, period, parameters):
        return person("medikids_group_rate_cost", period) * person("medicaid_federal_share", period)


# --- Variables the bill replaces ---------------------------------------------


class is_medicaid_eligible(Variable):
    value_type = bool
    entity = Person
    label = "Eligible for Medicaid"
    definition_period = YEAR
    documentation = (
        "Eligible through an existing group, or through the bill's group for everyone "
        "under 26 (no income, immigration-status or community engagement test)."
    )
    reference = "https://www.law.cornell.edu/uscode/text/42/1396a#a_10"

    def formula(person, period, parameters):
        existing = person("medikids_existing_group_eligible", period)
        return existing | person("medikids_under_26", period)


class medicaid_enrolled(Variable):
    value_type = bool
    entity = Person
    label = "Medicaid enrolled"
    definition_period = YEAR
    documentation = (
        "People eligible through an existing group enroll if the dataset's take-up flag "
        "says so, or if the switching case moves them in. People eligible only through "
        "the under-26 group enroll only if the switching case says so."
    )
    reference = "https://www.law.cornell.edu/uscode/text/42/1396a"
    defined_for = "is_medicaid_eligible"

    def formula(person, period, parameters):
        existing = person("medikids_existing_group_eligible", period)
        stored = person("takes_up_medicaid_if_eligible", period)
        chosen = person("medikids_case_enrolls", period)
        return where(existing, stored | chosen, chosen)


# --- Reform builders ---------------------------------------------------------


_UNSCALED = "medikids_unscaled_value"


def _scale_by_state(node, factor: float) -> None:
    """Multiply each state's value in the reporting year by ``factor``.

    The engine applies a reform's ``apply`` twice while it builds a system, so
    the unscaled value is remembered on the parameter and the scaling is the
    same however many times this runs.
    """
    for parameter in node.get_descendants():
        if not isinstance(parameter, Parameter):
            continue
        if _UNSCALED not in parameter.metadata:
            parameter.metadata[_UNSCALED] = parameter(_START)
        parameter.update(start=_START, stop=_STOP, value=parameter.metadata[_UNSCALED] * factor)


def _grow_cost_inputs(parameters):
    """Grow the engine's flat calibration totals to the reporting year."""
    calibration = parameters.calibration.gov.hhs
    _scale_by_state(calibration.medicaid.totals.spending, A.model_allocation_growth())
    _scale_by_state(calibration.cms.chip.spending.separate_chip.total, A.chip_growth())
    return parameters


def _apply_bill_parameters(parameters):
    # New 36B(c)(2)(D): eligibility through the under-26 group alone is not
    # minimum essential coverage. The Marketplace gate keeps blocking on
    # eligibility through existing groups; enrollment already blocks through
    # gov.aca.qualifying_non_marketplace_health_coverage.
    gate = parameters.gov.aca.ineligible_coverage
    names = [
        "medikids_existing_group_eligible" if name == "is_medicaid_eligible" else name
        for name in gate(_START)
    ]
    gate.update(start=_START, stop=_STOP, value=names)
    # Section 2(g): everyone under 26 is excepted from community engagement
    # requirements, so the requirement's age range starts at 26.
    age_range = parameters.gov.hhs.medicaid.eligibility.work_requirements.age_range
    age_range.brackets[1].threshold.update(start=_START, stop=_STOP, value=A.AGE_LIMIT)
    return parameters


_SHARED_VARIABLES = (
    medikids_under_26,
    medikids_federal_immigration_eligible,
    medikids_existing_group_eligible,
    medikids_lookback_eligible,
    medikids_lookback_adult_group,
    medikids_in_aca_adult_group,
    medikids_case_enrolls,
    medikids_group_rate,
    medikids_group_rate_cost,
    medikids_group_rate_federal_cost,
)


# The engine calls a reform's ``apply`` twice while it builds a system, so every
# step below is written to give the same result on a second pass: variables are
# registered with ``update_variable`` and parameter changes are idempotent.


def current_law_reform() -> type[Reform]:
    """Current law with this analysis's cost conventions. No one's coverage changes."""

    class current_law(Reform):
        def apply(self):
            for variable in _SHARED_VARIABLES:
                self.update_variable(variable)
            self.update_variable(_share_variable("medicaid_federal_share", "current_law"))
            self.modify_parameters(_grow_cost_inputs)

    return current_law


def medikids_reform() -> type[Reform]:
    """The bill, on top of the current-law cost conventions."""

    class medikids(Reform):
        def apply(self):
            for variable in _SHARED_VARIABLES:
                self.update_variable(variable)
            self.update_variable(_share_variable("medicaid_federal_share", "primary"))
            for variable in alternative_reading_variables():
                self.update_variable(variable)
            self.update_variable(is_medicaid_eligible)
            self.update_variable(medicaid_enrolled)
            self.modify_parameters(_grow_cost_inputs)
            self.modify_parameters(_apply_bill_parameters)

    return medikids


# Filled by the lookback reform each time it is applied: the parameters with no
# value dated on or before the lookback date, which are left alone. The
# lookback stage records them in its provenance file.
SKIPPED_AT_LOOKBACK: list[str] = []


def pin_to_lookback_date(parameters) -> list[str]:
    """Pin Medicaid and CHIP eligibility parameters to their 2025-01-01 values.

    Returns the names of parameters with no value dated on or before that date,
    which are left alone. The engine backdates the first value of most
    parameters, so this list can be empty even for rules first enacted later
    (the community engagement requirement is pinned to off through its on/off
    switch). The state folders are pinned whole, so a few parameters outside
    Medicaid are pinned as well.
    """
    pin = instant(A.LOOKBACK_DATE)
    skipped = []
    for path in LOOKBACK_SUBTREES:
        node = parameters
        for part in path.split("."):
            node = getattr(node, part)
        for parameter in node.get_descendants():
            if not isinstance(parameter, Parameter):
                continue
            dated_by_then = any(v.instant_str <= A.LOOKBACK_DATE for v in parameter.values_list)
            value = parameter(pin) if dated_by_then else None
            if value is None:
                skipped.append(parameter.name)
                continue
            parameter.update(start=_START, stop=_STOP, value=value)
    return skipped


class medikids_lookback_title_xix_eligible(Variable):
    value_type = bool
    entity = Person
    definition_period = YEAR
    label = "Eligible under the title XIX State plan (computed in the lookback run)"
    documentation = (
        "A Medicaid category under the pinned 2025-01-01 rules, or California's former "
        "foster youth group, together with the federal immigration test. It leaves out "
        "state-funded coverage and separate CHIP, which are not medical assistance under "
        "a title XIX State plan. The engine does not record whether a category gives full "
        "benefits, so every category counts as full benefits here."
    )

    def formula(person, period, parameters):
        category = person("medicaid_category", period)
        in_category = category != category.possible_values.NONE
        federal = person("medikids_federal_immigration_eligible", period)
        return (in_category | person("ca_ffyp_eligible", period)) & federal


def lookback_inputs(eligible, in_aca_adult_group, income_level) -> dict[str, np.ndarray]:
    """The two inputs the bill's match rates read, from the lookback run's outputs.

    ``eligible`` is ``medikids_lookback_title_xix_eligible``,
    ``in_aca_adult_group`` is ``medikids_in_aca_adult_group`` (the engine's
    ADULT category outside waiver states) and ``income_level``
    ``medicaid_income_level``, all from a simulation under ``lookback_reform``.
    A person counts as in the ACA adult group only up to that group's income
    limit: the expansion match does not reach people a state covered above it.
    """
    eligible = np.asarray(eligible, dtype=bool)
    in_aca_adult_group = np.asarray(in_aca_adult_group, dtype=bool)
    in_income_range = np.asarray(income_level, dtype=float) <= A.ADULT_GROUP_INCOME_LIMIT
    return {
        "medikids_lookback_eligible": eligible,
        "medikids_lookback_adult_group": eligible & in_aca_adult_group & in_income_range,
    }


def lookback_reform() -> type[Reform]:
    """Eligibility rules pinned to 2025-01-01, for the reporting year's population."""

    class lookback(Reform):
        def apply(self):
            self.update_variable(medikids_under_26)
            self.update_variable(medikids_federal_immigration_eligible)
            self.update_variable(medikids_lookback_title_xix_eligible)
            self.update_variable(medikids_in_aca_adult_group)

            def pin(parameters):
                SKIPPED_AT_LOOKBACK[:] = pin_to_lookback_date(parameters)
                return parameters

            self.modify_parameters(pin)

    return lookback
