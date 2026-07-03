"""TFM MDPDP — one JModel, seventeen datasets (S6 bridge content).

The owner's TFM (Vall-llaura 2017, §2.2 "Proposta d'un nou model", eqs. 4.1–4.10)
formulates a multi-depot pickup-and-delivery assignment as a flow problem over the
sparse arc set A′: every vehicle k has its own start sₖ and end eₖ, every order is a
load→unload pair (c, d), and A′ is tripartite — start→load, the paired load→unload,
unload→end. This module holds that formulation ONCE as a JModel (structure) plus the
per-scenario data builders (Table 3 real data + Table 4 synthetic sizes) that
``scripts/tfm_bridge.py`` turns into named datasets.

Everything here is pure and deterministic — the bridge and the regression tests
share it. The known optimum of the fabricated Table 3 instance is 90 (thesis §3.1.1:
V1→T1 = 14, V2→T2 = 42, V3→T3 = 34, V4 idle).
"""

from __future__ import annotations

import random

#: The thesis "nou model" (4.1–4.10) as a declaration-only JModel: each dataset fills
#: the same structure. Arc layers are 3-dimensional tuple sets (i, j, k) ⊂ A′, so
#: variables exist only for the arcs the scenario actually contains.
MDPDP_JMODEL = """\
# MDPDP — Vall-llaura (2017) TFM, "nou model" (thesis §2.2, eqs. 4.1-4.10).
# One model, many datasets: every TFM scenario fills these declarations.
# A' is tripartite: start->load, the paired load->unload, unload->end.

set K;              # vehicles
set C;              # load (pickup) nodes, one per client order
set SC dimen 3;     # (s_k, c, k) in A' — valid start->load arcs
set CD dimen 3;     # (c, d_c, k) in A' — the paired load->unload arcs
set DE dimen 3;     # (d, e_k, k) in A' — valid unload->end arcs

param dist_sc{SC};  # d_ij per arc (km)
param dist_cd{CD};
param dist_de{DE};
param fuel{K};      # L_k — consumption per km of vehicle k
param rmax{K};      # R_k — max distance allowed for vehicle k
param benefit{C};   # b_i — expected profit of dispatching order i
param alpha;        # transport-cost weight
param gamma;        # unserved-order penalty weight

var xsc{SC} binary; # X_ijk on each arc layer of A'
var xcd{CD} binary;
var xde{DE} binary;
var z{C} binary;    # Z_i = 1 when order i is NOT dispatched

# (4.1) minimize alpha * sum d_ij * L_k * X_ijk + gamma * sum b_i * Z_i
minimize total_cost:
      sum{(s, c, k) in SC} alpha * fuel[k] * dist_sc[s, c, k] * xsc[s, c, k]
    + sum{(c, d, k) in CD} alpha * fuel[k] * dist_cd[c, d, k] * xcd[c, d, k]
    + sum{(d, e, k) in DE} alpha * fuel[k] * dist_de[d, e, k] * xde[d, e, k]
    + sum{c in C} gamma * benefit[c] * z[c];

# (4.2) going start->load forces the paired load->unload by the same vehicle
subject to load_to_unload{(c, d, k) in CD}:
    sum{(s, c2, k2) in SC : c2 == c and k2 == k} xsc[s, c2, k2] - xcd[c, d, k] == 0;

# (4.3) going load->unload forces unload->that vehicle's end point
subject to unload_to_end{(c, d, k) in CD}:
    xcd[c, d, k] - sum{(d2, e, k2) in DE : d2 == d and k2 == k} xde[d2, e, k2] == 0;

# (4.4) a vehicle that leaves its start reaches its end
subject to start_to_end{k in K}:
    sum{(s, c, k2) in SC : k2 == k} xsc[s, c, k2]
      - sum{(d, e, k3) in DE : k3 == k} xde[d, e, k3] == 0;

# (4.5)+(4.10) every order is dispatched by exactly one vehicle, or penalized
subject to dispatch{c in C}:
    sum{(c2, d, k) in CD : c2 == c} xcd[c2, d, k] + z[c] == 1;

# (4.6) a vehicle leaves its start at most once
subject to start_once{k in K}:
    sum{(s, c, k2) in SC : k2 == k} xsc[s, c, k2] <= 1;

# (4.7) no vehicle exceeds its max allowed distance
subject to max_distance{k in K}:
      sum{(s, c, k2) in SC : k2 == k} dist_sc[s, c, k2] * xsc[s, c, k2]
    + sum{(c, d, k3) in CD : k3 == k} dist_cd[c, d, k3] * xcd[c, d, k3]
    + sum{(d, e, k4) in DE : k4 == k} dist_de[d, e, k4] * xde[d, e, k4] <= rmax[k];
"""

#: Thesis Table 3 ("Dades de l'escenari fabricat"): total path cost per
#: (vehicle, order) pairing. Known optimum 90 = 14 + 42 + 34 with V4 idle.
TABLE_3_COSTS: list[list[float]] = [
    [14, 65, 90],
    [30, 42, 76],
    [62, 17, 34],
    [14, 65, 90],
]

#: Thesis Table 4 sizes (vehicles × orders), in thesis order. scenario_00 is the
#: fabricated Table 3 instance; 01–16 carry synthetic data at these sizes and are
#: comparable on solve time / scaling only.
TABLE_4_SIZES: list[tuple[int, int]] = [
    (3, 3),
    (4, 4),
    (10, 10),
    (15, 15),
    (20, 20),
    (24, 10),
    (25, 25),
    (30, 30),
    (40, 40),
    (50, 50),
    (70, 70),
    (100, 100),
    (115, 115),
    (150, 150),
    (200, 200),
    (243, 199),
]

#: Large-vs-route penalty weight: any dispatch (max cost per pairing < 1000) beats
#: leaving an order unserved, matching the thesis's "gran valor de penalització".
GAMMA = 100_000.0

SCENARIO_00_NAME = "scenario_00_fabricated_4x3"


def _dataset(
    vehicles: int,
    orders: int,
    dist_sc: dict[str, float],
    dist_cd: dict[str, float],
    dist_de: dict[str, float],
    rmax: float,
) -> dict:
    """Assemble the dataset ``data_json`` shape shared by all scenarios.

    Node names follow the thesis graph: vehicle k has start ``s{k}`` and end
    ``e{k}``; order t is the load–unload pair ``c{t}``/``d{t}``.
    """
    ks = [f"k{v}" for v in range(1, vehicles + 1)]
    cs = [f"c{t}" for t in range(1, orders + 1)]
    return {
        "sets": {
            "K": ks,
            "C": cs,
            "SC": list(dist_sc),
            "CD": list(dist_cd),
            "DE": list(dist_de),
        },
        "params": {
            "dist_sc": dist_sc,
            "dist_cd": dist_cd,
            "dist_de": dist_de,
            "fuel": {k: 1.0 for k in ks},
            "rmax": {k: rmax for k in ks},
            "benefit": {c: 1.0 for c in cs},
            "alpha": 1.0,
            "gamma": GAMMA,
        },
    }


def scenario_00_data() -> dict:
    """The fabricated Table 3 instance (4 vehicles × 3 orders), optimum 90.

    Table 3 states the TOTAL path cost of each (vehicle, order) pairing; the
    fabricated instance carries it on the approach leg (start→load — the thesis's
    "empty km" X) with zero-length load→unload and unload→end legs.
    """
    vehicles, orders = 4, 3
    dist_sc = {
        f"s{v},c{t},k{v}": float(TABLE_3_COSTS[v - 1][t - 1])
        for v in range(1, vehicles + 1)
        for t in range(1, orders + 1)
    }
    dist_cd = {f"c{t},d{t},k{v}": 0.0 for t in range(1, orders + 1) for v in range(1, vehicles + 1)}
    dist_de = {f"d{t},e{v},k{v}": 0.0 for t in range(1, orders + 1) for v in range(1, vehicles + 1)}
    return _dataset(vehicles, orders, dist_sc, dist_cd, dist_de, rmax=1000.0)


def synthetic_scenario_data(vehicles: int, orders: int, seed: int) -> dict:
    """A synthetic instance at a Table 4 size (deterministic for a given seed).

    Distances are drawn once per arc: approach and return legs 10–150 km, the
    order's load→unload leg 20–400 km (vehicle-independent, like a real order).
    ``rmax`` stays non-binding so scenarios compare on size, not feasibility.
    """
    rng = random.Random(seed)
    approach = {
        (v, t): float(rng.randint(10, 150))
        for v in range(1, vehicles + 1)
        for t in range(1, orders + 1)
    }
    haul = {t: float(rng.randint(20, 400)) for t in range(1, orders + 1)}
    retreat = {
        (t, v): float(rng.randint(10, 150))
        for t in range(1, orders + 1)
        for v in range(1, vehicles + 1)
    }
    dist_sc = {f"s{v},c{t},k{v}": cost for (v, t), cost in approach.items()}
    dist_cd = {
        f"c{t},d{t},k{v}": haul[t] for t in range(1, orders + 1) for v in range(1, vehicles + 1)
    }
    dist_de = {f"d{t},e{v},k{v}": cost for (t, v), cost in retreat.items()}
    return _dataset(vehicles, orders, dist_sc, dist_cd, dist_de, rmax=10_000.0)


def iter_scenarios() -> list[tuple[str, dict]]:
    """Every TFM scenario as ``(name, data_json)``, in thesis order.

    scenario_00 is the fabricated Table 3 instance (real data, optimum 90);
    scenario_01..16 are synthetic at the Table 4 sizes, seeded by their index.
    """
    scenarios: list[tuple[str, dict]] = [(SCENARIO_00_NAME, scenario_00_data())]
    for index, (vehicles, orders) in enumerate(TABLE_4_SIZES, start=1):
        name = f"scenario_{index:02d}_{vehicles}x{orders}"
        scenarios.append((name, synthetic_scenario_data(vehicles, orders, seed=index)))
    return scenarios
