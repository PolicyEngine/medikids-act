"""Shared fixtures: one set of households run under each reform.

Building a reformed tax-benefit system takes several seconds, so every
household goes into one situation and each reform is built once per session.
"""

from __future__ import annotations

import gc

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
    # Parent in the adult group today whose 2025 group was the parent group.
    "va_parent": ("VA", [("parent", 24, 9_000, "CITIZEN"), ("child", 3, 0, "CITIZEN")]),
    # DC adult above the adult group's income limit, covered in 2025 under DC's
    # higher limit and cut in 2026.
    "dc_adult": ("DC", [("adult", 23, 31_000, "CITIZEN")]),
    # California former foster youth, above every income limit.
    "ca_foster": ("CA", [("adult", 22, 60_000, "CITIZEN")]),
    # Wisconsin adult below the poverty line: covered through the BadgerCare
    # section 1115 waiver, which the engine files under its ADULT category.
    "wi_adult": ("WI", [("adult", 23, 9_000, "CITIZEN")]),
}
EXTRA_INPUTS = {"ca_foster.adult": {"was_in_foster_care": True}}


# Every household appears twice in one situation. The second copy is the one in
# which everyone under 26 enrolls, so a single simulation of the bill covers
# both enrollment patterns and the suite builds one reformed system fewer.
ENROLLING_COPY = "+enrolls"


def build_situation() -> tuple[dict, list[str]]:
    people, order = {}, []
    groups = {k: {} for k in ("tax_units", "spm_units", "families", "households", "marital_units")}
    copies = [(name, spec) for name, spec in HOUSEHOLDS.items()]
    copies += [(name + ENROLLING_COPY, spec) for name, spec in HOUSEHOLDS.items()]
    for name, (state, members) in copies:
        ids = []
        for person, age, income, status in members:
            pid = f"{name}.{person}"
            people[pid] = {
                "age": {Y: age},
                "employment_income": {Y: income},
                "immigration_status_str": {Y: status},
            }
            for variable, value in EXTRA_INPUTS.get(
                f"{name.replace(ENROLLING_COPY, '')}.{person}", {}
            ).items():
                people[pid][variable] = {Y: value}
            ids.append(pid)
            order.append(pid)
            groups["marital_units"][f"{pid}.mu"] = {"members": [pid]}
        groups["tax_units"][f"{name}.tu"] = {"members": ids}
        groups["spm_units"][f"{name}.spm"] = {"members": ids}
        groups["families"][f"{name}.fam"] = {"members": ids}
        groups["households"][f"{name}.hh"] = {"members": ids, "state_code": {Y: state}}
    return {"people": people, **groups}, order


class Run:
    """One copy of the households in a simulation, with name-based access."""

    def __init__(self, sim, order, copy=""):
        self.sim, self.order, self.copy = sim, order, copy

    def _mine(self, key: str) -> bool:
        return key.split(".")[0].endswith(ENROLLING_COPY) == bool(self.copy)

    def person(self, variable: str, period=Y) -> dict[str, object]:
        values = self.sim.calculate(variable, period, map_to="person")
        if hasattr(values, "decode_to_str"):
            values = values.decode_to_str()
        pairs = zip(self.order, np.asarray(values).tolist(), strict=True)
        return {key.replace(ENROLLING_COPY, ""): value for key, value in pairs if self._mine(key)}

    def tax_unit(self, variable: str) -> dict[str, float]:
        values = np.asarray(self.sim.calculate(variable, Y)).tolist()
        names = [*HOUSEHOLDS, *(name + ENROLLING_COPY for name in HOUSEHOLDS)]
        pairs = zip(names, values, strict=True)
        return {key.replace(ENROLLING_COPY, ""): value for key, value in pairs if self._mine(key)}

    def all_people(self, variable: str) -> np.ndarray:
        return np.asarray(self.sim.calculate(variable, Y, map_to="person"))


@pytest.fixture(scope="session")
def situation():
    return build_situation()


def _simulation(situation, reform=None):
    from policyengine_us import Simulation

    sit, _order = situation
    return Simulation(situation=sit, reform=reform) if reform else Simulation(situation=sit)


# Simulations are module-scoped and released afterwards: each holds its own
# copy of the tax-benefit system, and the suite should stay light.
@pytest.fixture(scope="module")
def engine(situation):
    yield Run(_simulation(situation), situation[1])
    gc.collect()


@pytest.fixture(scope="module")
def lookback(situation):
    from medikids_act.reform import lookback_reform

    yield Run(_simulation(situation, lookback_reform()), situation[1])
    gc.collect()


@pytest.fixture(scope="session")
def lookback_inputs(situation):
    """The two inputs the match rates read, computed once and kept as arrays."""
    from medikids_act.reform import lookback_inputs as build
    from medikids_act.reform import lookback_reform

    sim = _simulation(situation, lookback_reform())
    inputs = build(
        np.asarray(sim.calculate("medikids_lookback_title_xix_eligible", Y)),
        np.asarray(sim.calculate("medikids_in_aca_adult_group", Y)),
        np.asarray(sim.calculate("medicaid_income_level", Y)),
    )
    del sim
    gc.collect()
    return inputs


def _with_inputs(sim, inputs):
    for name, values in inputs.items():
        sim.set_input(name, Y, values)
    return sim


@pytest.fixture(scope="module")
def current_law(situation, lookback_inputs):
    from medikids_act.reform import current_law_reform

    sim = _with_inputs(_simulation(situation, current_law_reform()), lookback_inputs)
    yield Run(sim, situation[1])
    gc.collect()


@pytest.fixture(scope="module")
def _bill(situation, lookback_inputs):
    """The bill, simulated once: nobody chooses to enroll in the first copy of
    each household, and everyone under 26 enrolls in the second."""
    from medikids_act.reform import medikids_reform

    sit, order = situation
    sim = _with_inputs(_simulation(situation, medikids_reform()), lookback_inputs)
    enrolls = [
        ENROLLING_COPY in person and sit["people"][person]["age"][Y] < A.AGE_LIMIT
        for person in order
    ]
    sim.set_input("medikids_case_enrolls", Y, np.array(enrolls))
    yield sim, order
    gc.collect()


@pytest.fixture(scope="module")
def bill_nobody(_bill):
    """The bill with nobody choosing to enroll and no forced moves."""
    return Run(*_bill)


@pytest.fixture(scope="module")
def bill_everyone(_bill):
    """The bill with every person under 26 enrolling."""
    return Run(*_bill, copy=ENROLLING_COPY)
