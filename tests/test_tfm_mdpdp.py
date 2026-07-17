"""TFM MDPDP JModel + datasets (S6 bridge content) — the thesis-optimum contract.

The MDPDP JModel in :mod:`app.data.tfm_mdpdp` is the structure every TFM scenario
dataset fills. The fabricated Table 3 instance (scenario_00) has a known optimum of
90 in the thesis (§3.1.1) — solving the compiled model through the real SCIP adapter
must reproduce it exactly.
"""

import pytest

from app.data.tfm_mdpdp import (
    MDPDP_JMODEL,
    SCENARIO_00_NAME,
    TABLE_4_SIZES,
    iter_scenarios,
    scenario_00_data,
    synthetic_scenario_data,
)
from app.domains.dsl import JModelData, compile_jmodel

pytestmark = pytest.mark.unit


def _compile(data_json: dict):
    return compile_jmodel(MDPDP_JMODEL, data=JModelData.from_json(data_json))


def test_scenario_00_grounds_sparse():
    prob = _compile(scenario_00_data())

    # 4 vehicles x 3 orders: 12 arcs per layer + 3 unserved flags — and ONLY those
    names = [v.name for v in prob.variables]
    assert len(names) == 39
    assert "xsc_s1_c1_k1" in names and "z_c3" in names
    # a vehicle never uses another vehicle's start: (s1, c1, k2) is not an arc
    assert "xsc_s1_c1_k2" not in names

    by_name = {c.name: c.expression for c in prob.constraints}
    # (4.2) pairs the approach with the order's own haul, per vehicle
    assert by_name["load_to_unload_c1_d1_k1"] == "xsc_s1_c1_k1 - xcd_c1_d1_k1 == 0"
    # (4.10) each order dispatched once or penalized
    assert by_name["dispatch_c1"] == (
        "xcd_c1_d1_k1 + xcd_c1_d1_k2 + xcd_c1_d1_k3 + xcd_c1_d1_k4 + z_c1 == 1"
    )


# CONTRACT-TEST: the scenario_00 dataset solves the MDPDP JModel to the thesis
# optimum 90 through the real solver — the S6 acceptance criterion. If this breaks,
# the JModel, the dataset builders, or the compiler changed semantics.
def test_scenario_00_solves_to_thesis_optimum_90():
    from app.domains.solver.adapters.scip import SCIPAdapter

    result = SCIPAdapter().solve(_compile(scenario_00_data()))

    assert result.status.value == "optimal"
    assert result.objective_value is not None
    assert abs(result.objective_value - 90.0) < 1e-6
    assert result.solution is not None
    # thesis §3.1.1 expected pairing: V1-T1 (14), V2-T2 (42), V3-T3 (34); V4 idle
    # (V4 duplicates V1's row, so the mirrored pairing is an equally-valid optimum)
    dispatched = {n for n, v in result.solution.items() if n.startswith("xcd_") and v > 0.5}
    assert len(dispatched) == 3
    unserved = {n for n, v in result.solution.items() if n.startswith("z_") and v > 0.5}
    assert unserved == set()


def test_synthetic_scenario_compiles_and_solves_all_orders():
    from app.domains.solver.adapters.scip import SCIPAdapter

    prob = _compile(synthetic_scenario_data(10, 10, seed=3))
    assert len(prob.variables) == 3 * 10 * 10 + 10

    result = SCIPAdapter().solve(prob)
    assert result.status.value == "optimal"
    assert result.objective_value is not None
    # 10 vehicles cover 10 orders: the 100k-per-order penalty never pays off
    assert result.objective_value < 100_000


def test_scenario_names_match_the_thesis_grid():
    names = [name for name, _ in iter_scenarios()]
    assert names[0] == SCENARIO_00_NAME
    assert names[1] == "scenario_01_3x3"
    assert names[6] == "scenario_06_24x10"
    assert names[16] == "scenario_16_243x199"
    assert len(names) == len(TABLE_4_SIZES) + 1


def test_scenario_data_is_deterministic():
    a = synthetic_scenario_data(24, 10, seed=6)
    b = synthetic_scenario_data(24, 10, seed=6)
    assert a == b
    # a different seed actually changes the draw (guards a silently-ignored seed)
    assert a != synthetic_scenario_data(24, 10, seed=7)
