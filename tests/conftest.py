"""Shared fixtures: one set of households run under each reform.

Building a reformed tax-benefit system takes several seconds, so every
household goes into one situation and each reform is built once per session.
"""

from __future__ import annotations

import numpy as np
import pytest

from medikids_act import assumptions as A

Y = A.YEAR

# name -> (state, [(person, age, employment income, immigration status)])
HOUSEHOLDS = {
    # Separate-CHIP child, and a 22-year-old with no Medicaid group, in a non-expansion state.
    "tx_chip": (
        "TX",
        [
            ("parent", 40, 60_000, "CITIZEN"),
            ("child", 10, 0, "CITIZEN"),
            ("young", 22, 0, "CITIZEN"),
        ],
    ),
    # Child above the CHIP limit: a Marketplace family with a premium tax credit.
    "tx_marketplace": ("TX", [("parent", 40, 70_000, "CITIZEN"), ("child", 10, 0, "CITIZEN")]),
    # ACA adult group member who fails the community engagement requirement.
    "ca_adult": ("CA", [("adult", 23, 0, "CITIZEN")]),
    # Undocumented child where the state does not cover undocumented people.
    "tx_undocumented": (
        "TX",
        [("parent", 40, 20_000, "UNDOCUMENTED"), ("child", 10, 0, "UNDOCUMENTED")],
    ),
    # Undocumented child in state-funded coverage.
    "ny_undocumented": (
        "NY",
        [("parent", 40, 20_000, "UNDOCUMENTED"), ("child", 10, 0, "UNDOCUMENTED")],
    ),
    # Child in a Medicaid child group today.
    "ca_child": ("CA", [("parent", 40, 20_000, "CITIZEN"), ("child", 5, 0, "CITIZEN")]),
    # Basic Health Program enrollee under 26.
    "mn_bhp": ("MN", [("adult", 22, 30_000, "CITIZEN")]),
    # Adult over 26 with no Medicaid group: the bill does not reach them.
    "tx_older": ("TX", [("adult", 30, 15_000, "CITIZEN")]),
    # Refugee adult: eligible under the 2025 list, cut by the October 2026 change.
    "ny_refugee": ("NY", [("adult", 22, 0, "REFUGEE")]),
}


def build_situation() -> tuple[dict, list[str]]:
    people, order = {}, []
    groups = {k: {} for k in ("tax_units", "spm_units", "families", "households", "marital_units")}
    for name, (state, members) in HOUSEHOLDS.items():
        ids = []
        for person, age, income, status in members:
            pid = f"{name}.{person}"
            people[pid] = {
                "age": {Y: age},
                "employment_income": {Y: income},
                "immigration_status_str": {Y: status},
            }
            ids.append(pid)
            order.append(pid)
            groups["marital_units"][f"{pid}.mu"] = {"members": [pid]}
        groups["tax_units"][f"{name}.tu"] = {"members": ids}
        groups["spm_units"][f"{name}.spm"] = {"members": ids}
        groups["families"][f"{name}.fam"] = {"members": ids}
        groups["households"][f"{name}.hh"] = {"members": ids, "state_code": {Y: state}}
    return {"people": people, **groups}, order


class Run:
    """A simulation plus name-based access to its people."""

    def __init__(self, sim, order):
        self.sim, self.order = sim, order

    def person(self, variable: str, period=Y) -> dict[str, object]:
        values = self.sim.calculate(variable, period, map_to="person")
        if hasattr(values, "decode_to_str"):
            values = values.decode_to_str()
        return dict(zip(self.order, np.asarray(values).tolist(), strict=True))

    def tax_unit(self, variable: str) -> dict[str, float]:
        values = np.asarray(self.sim.calculate(variable, Y))
        return dict(zip(HOUSEHOLDS, values.tolist(), strict=True))


@pytest.fixture(scope="session")
def situation():
    return build_situation()


@pytest.fixture(scope="session")
def engine(situation):
    from policyengine_us import Simulation

    sit, order = situation
    return Run(Simulation(situation=sit), order)


@pytest.fixture(scope="session")
def lookback(situation):
    from policyengine_us import Simulation

    from medikids_act.reform import lookback_reform

    sit, order = situation
    return Run(Simulation(situation=sit, reform=lookback_reform()), order)


@pytest.fixture(scope="session")
def lookback_inputs(lookback):
    eligible = lookback.person("medikids_lookback_title_xix_eligible")
    category = lookback.person("medicaid_category")
    return {
        "medikids_lookback_eligible": np.array([eligible[p] for p in lookback.order]),
        "medikids_lookback_adult_group": np.array(
            [eligible[p] and category[p] == "ADULT" for p in lookback.order]
        ),
    }


def _with_inputs(sim, inputs):
    for name, values in inputs.items():
        sim.set_input(name, Y, values)
    return sim


@pytest.fixture(scope="session")
def current_law(situation, lookback_inputs):
    from policyengine_us import Simulation

    from medikids_act.reform import current_law_reform

    sit, order = situation
    return Run(
        _with_inputs(Simulation(situation=sit, reform=current_law_reform()), lookback_inputs), order
    )


def _bill(situation, lookback_inputs, enrolls):
    from policyengine_us import Simulation

    from medikids_act.reform import medikids_reform

    sit, order = situation
    sim = _with_inputs(Simulation(situation=sit, reform=medikids_reform()), lookback_inputs)
    sim.set_input("medikids_case_enrolls", Y, np.array([enrolls(p) for p in order]))
    return Run(sim, order)


@pytest.fixture(scope="session")
def bill_nobody(situation, lookback_inputs):
    """The bill with nobody choosing to enroll and no forced moves."""
    return _bill(situation, lookback_inputs, lambda person: False)


@pytest.fixture(scope="session")
def bill_everyone(situation, lookback_inputs):
    """The bill with every person under 26 enrolling."""
    sit, _ = situation
    return _bill(
        situation,
        lookback_inputs,
        lambda person: sit["people"][person]["age"][Y] < A.AGE_LIMIT,
    )
