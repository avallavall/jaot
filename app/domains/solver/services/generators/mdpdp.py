"""MDPDP-TW-T generator — Multiple Depot Pickup and Delivery Problem.

Complete formulation with:
- Soft time windows (high penalty for tardiness)
- EU/Spanish tachograph (EC 561/2006): 4.5h continuous, 9h/10h daily, breaks
- Vehicle composition: tractor + trailer + driver assignment
- Load tracking with capacity enforcement

Based on Vall-llaura (2017) TFM formulation, extended with time windows,
tachograph constraints, and 3-way vehicle composition.
"""

import math
from collections import defaultdict
from typing import Any

from app.domains.solver.services.generators.base import (
    BaseGenerator,
    add_symmetry_breaking,
    build_reachable_nodes,
    compute_arc_big_m,
    find_list_field,
    safe_float,
)
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)

# Node type constants
NT_ORIGIN = "origin"
NT_ENDPOINT = "endpoint"
NT_PICKUP = "pickup"
NT_DELIVERY = "delivery"
NT_REST_STOP = "rest_stop"

# EC 561/2006 tachograph constants
TACHO_CONTINUOUS_DRIVE_MAX = 4.5  # hours
TACHO_BREAK_DURATION = 0.75  # 45 minutes
TACHO_DAILY_DRIVE_STD = 9.0  # hours
TACHO_DAILY_DRIVE_EXT = 10.0  # hours (max 2x/week)

ARC_DISTANCE_THRESHOLD = 0.8
REST_STOP_THRESHOLD = 4.0
REST_STOP_HORIZON = 999.0  # wide time window for rest-stop nodes


class MDPDPGenerator(BaseGenerator):
    """Generate Multi-Depot Pickup-Delivery problems with time windows and tachograph.

    Input: orders (pickup/delivery pairs), vehicles (tractors, trailers, drivers),
    distances, time windows. Output: assignment of orders to composite vehicles
    minimizing transport cost + tardiness penalty + unserved penalty.
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        orders = find_list_field(user_input, ["orders", "shipments", "loads"])
        if not orders:
            raise ValueError(f"MDPDP requires an orders list. Got keys: {list(user_input.keys())}")

        config = user_input.get("config", {})
        alpha = safe_float(config.get("alpha", params.get("alpha", 1.0)), "alpha")
        beta = safe_float(config.get("beta", params.get("beta", 1000.0)), "beta")
        gamma = safe_float(config.get("gamma", params.get("gamma", 5000.0)), "gamma")
        tacho_enabled = str(
            config.get("tachograph_enabled", params.get("tachograph_enabled", True))
        ).lower() not in ("false", "0", "no", "off")
        max_dist_default = safe_float(config.get("max_distance_per_vehicle", 800), "max_distance")
        time_limit = int(config.get("time_limit_seconds", 600))

        tractors: list[dict[str, Any]] = user_input.get("tractors", [])
        trailers: list[dict[str, Any]] = user_input.get("trailers", [])
        drivers: list[dict[str, Any]] = user_input.get("drivers", [])
        depots: list[dict[str, Any]] = user_input.get("depots", [])
        dist_data: list[dict[str, Any]] = user_input.get("distances", [])

        resource_counts = [len(tractors), len(trailers), len(drivers)]
        nonzero = [c for c in resource_counts if c > 0]
        if len(nonzero) > 1 and len(set(nonzero)) > 1:
            raise ValueError(
                f"Mismatched resource counts: {len(tractors)} tractors, "
                f"{len(trailers)} trailers, {len(drivers)} drivers. "
                "All non-empty resource lists must have the same length."
            )

        dist_map, time_map = self._build_distance_maps(dist_data)

        n_vehicles = max(len(tractors), len(trailers), len(drivers), 1)
        n_orders = len(orders)

        nodes = self._build_nodes(orders, tractors, depots, n_vehicles)

        # Insert rest-stop nodes on long arcs when tachograph is enabled
        # Only for location pairs used by actual problem nodes (orders + depots)
        blocked_loc_pairs: set[tuple[str, str]] = set()
        if tacho_enabled:
            active_locs = {n_data.get("location", "") for n_data in nodes.values()} - {""}
            rest_nodes, dist_map, time_map, blocked_loc_pairs = self._insert_rest_stops(
                dist_map, time_map, active_locations=active_locs
            )
            nodes.update(rest_nodes)

        valid_arcs = self._build_valid_arcs(
            nodes,
            n_vehicles,
            n_orders,
            dist_map,
            max_dist_default,
            blocked_loc_pairs=blocked_loc_pairs,
        )

        # P1: Vehicle-order compatibility filtering (S2)
        valid_arcs = self._filter_vehicle_order_arcs(
            valid_arcs, nodes, n_vehicles, n_orders, time_map
        )

        # Adjacency indices for O(1) lookups
        out_by_nk: dict[tuple[str, int], list[str]] = defaultdict(list)
        in_by_nk: dict[tuple[str, int], list[str]] = defaultdict(list)
        for i, j, k in valid_arcs:
            out_by_nk[(i, k)].append(j)
            in_by_nk[(j, k)].append(i)

        # P0: Reachability — only create vars for (node, vehicle) with arcs
        reachable_by_k = build_reachable_nodes(valid_arcs)

        customer_nodes = frozenset(n for n in nodes if nodes[n]["type"] in (NT_PICKUP, NT_DELIVERY))
        breakable_nodes = frozenset(
            n for n in nodes if nodes[n]["type"] in (NT_PICKUP, NT_DELIVERY, NT_REST_STOP)
        )

        # Precompute arc distance and time (once per node pair)
        arc_dist: dict[tuple[str, str], float] = {}
        arc_time: dict[tuple[str, str], float] = {}
        for i, j, _k in valid_arcs:
            if (i, j) not in arc_dist:
                loc_i = nodes[i].get("location", i)
                loc_j = nodes[j].get("location", j)
                arc_dist[(i, j)] = dist_map.get((loc_i, loc_j), dist_map.get((i, j), 0))
                arc_time[(i, j)] = time_map.get((loc_i, loc_j), time_map.get((i, j), 0))

        # Big-M values
        all_times = [t for t in time_map.values() if t > 0]
        max_travel = max(all_times) if all_times else 10.0
        all_service = [nodes[n].get("service_time", 0) for n in nodes]
        max_service = max(all_service) if all_service else 0.5
        all_latest = [nodes[n].get("latest", 24) for n in customer_nodes]
        max_latest = max(all_latest) if all_latest else 24.0

        # Variable upper bound: planning horizon
        m_time = max_latest + max_travel + max_service + 1.0
        # Global big-M fallback (worst-case per-arc M where a_j=0)
        big_m_global = (
            m_time + max_travel + max_service + 1.0
        )  # = compute_arc_big_m(worst, {}, max_travel, m_time)
        m_load = max((tl.get("capacity_pallets", 33) for tl in trailers), default=33)
        m_drive = TACHO_DAILY_DRIVE_EXT

        # P2: Per-arc big-M via shared utility
        arc_big_m: dict[tuple[str, str], float] = {}
        for i, j, _k in valid_arcs:
            if (i, j) not in arc_big_m:
                arc_big_m[(i, j)] = compute_arc_big_m(
                    nodes[i], nodes[j], arc_time.get((i, j), 0), m_time
                )

        variables: list[Variable] = []
        obj_terms: list[str] = []
        constraints: list[Constraint] = []

        # X_ijk: binary routing arcs
        x_vars: dict[tuple[str, str, int], str] = {}
        for i, j, k in valid_arcs:
            vn = f"x_{i}_{j}_{k}"
            variables.append(Variable(name=vn, type=VariableType.BINARY))
            x_vars[(i, j, k)] = vn
            d = arc_dist[(i, j)]
            fuel = tractors[k].get("fuel_cost_per_km", 0.35) if k < len(tractors) else 0.35
            if d > 0:
                obj_terms.append(f"{round(alpha * d * fuel, 4)}*{vn}")

        # Z_i: unserved order penalty
        z_vars: dict[int, str] = {}
        for idx in range(n_orders):
            vn = f"z_{idx}"
            variables.append(Variable(name=vn, type=VariableType.BINARY))
            z_vars[idx] = vn
            benefit = safe_float(
                orders[idx].get("benefit", orders[idx].get("priority", 1)), "benefit"
            )
            obj_terms.append(f"{round(gamma * benefit, 4)}*{vn}")

        # S_ik: arrival time — reachable pairs, earliest as lower bound
        s_vars: dict[tuple[str, int], str] = {}
        for node_id in nodes:
            for k in range(n_vehicles):
                if node_id not in reachable_by_k[k]:
                    continue
                lb = nodes[node_id].get("earliest", 0)
                vn = f"s_{node_id}_{k}"
                variables.append(
                    Variable(
                        name=vn, type=VariableType.CONTINUOUS, lower_bound=lb, upper_bound=m_time
                    )
                )
                s_vars[(node_id, k)] = vn

        # L_ik: load — only for reachable customer (node, vehicle) pairs
        l_vars: dict[tuple[str, int], str] = {}
        for node_id in customer_nodes:
            for k in range(n_vehicles):
                if node_id not in reachable_by_k[k]:
                    continue
                vn = f"l_{node_id}_{k}"
                variables.append(
                    Variable(
                        name=vn, type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=m_load
                    )
                )
                l_vars[(node_id, k)] = vn

        # T_i: tardiness at customer nodes
        t_vars: dict[str, str] = {}
        for node_id in customer_nodes:
            vn = f"tard_{node_id}"
            variables.append(Variable(name=vn, type=VariableType.CONTINUOUS, lower_bound=0))
            t_vars[node_id] = vn
            obj_terms.append(f"{beta}*{vn}")

        # Y_k: vehicle used
        y_vars: dict[int, str] = {}
        for k in range(n_vehicles):
            vn = f"y_{k}"
            variables.append(Variable(name=vn, type=VariableType.BINARY))
            y_vars[k] = vn

        # Tachograph variables
        h_vars: dict[tuple[str, int], str] = {}
        b_vars: dict[tuple[str, int], str] = {}
        w_vars: dict[tuple[str, int], str] = {}
        e_vars: dict[int, str] = {}
        if tacho_enabled:
            for node_id in nodes:
                for k in range(n_vehicles):
                    if node_id not in reachable_by_k[k]:
                        continue
                    h_name = f"h_{node_id}_{k}"
                    variables.append(
                        Variable(
                            name=h_name,
                            type=VariableType.CONTINUOUS,
                            lower_bound=0,
                            upper_bound=TACHO_CONTINUOUS_DRIVE_MAX,
                        )
                    )
                    h_vars[(node_id, k)] = h_name
                    w_name = f"w_{node_id}_{k}"
                    variables.append(
                        Variable(
                            name=w_name,
                            type=VariableType.CONTINUOUS,
                            lower_bound=0,
                            upper_bound=TACHO_DAILY_DRIVE_EXT,
                        )
                    )
                    w_vars[(node_id, k)] = w_name

            for node_id in breakable_nodes:
                for k in range(n_vehicles):
                    if node_id not in reachable_by_k[k]:
                        continue
                    b_name = f"brk_{node_id}_{k}"
                    variables.append(Variable(name=b_name, type=VariableType.BINARY))
                    b_vars[(node_id, k)] = b_name

            for k in range(n_vehicles):
                e_name = f"ext_{k}"
                variables.append(Variable(name=e_name, type=VariableType.BINARY))
                e_vars[k] = e_name

        # Vehicle composition variables
        a_tr: dict[tuple[int, int], str] = {}
        a_tl: dict[tuple[int, int], str] = {}
        a_dr: dict[tuple[int, int], str] = {}
        if tractors and trailers and drivers:
            for t_idx in range(len(tractors)):
                for k in range(n_vehicles):
                    vn = f"atr_{t_idx}_{k}"
                    variables.append(Variable(name=vn, type=VariableType.BINARY))
                    a_tr[(t_idx, k)] = vn
            for l_idx in range(len(trailers)):
                for k in range(n_vehicles):
                    vn = f"atl_{l_idx}_{k}"
                    variables.append(Variable(name=vn, type=VariableType.BINARY))
                    a_tl[(l_idx, k)] = vn
            for d_idx in range(len(drivers)):
                for k in range(n_vehicles):
                    vn = f"adr_{d_idx}_{k}"
                    variables.append(Variable(name=vn, type=VariableType.BINARY))
                    a_dr[(d_idx, k)] = vn

        # C1: Each served order visited exactly once (pickup)
        for idx in range(n_orders):
            p_node = f"p_{idx}"
            terms = [
                x_vars[(p_node, j, k)]
                for k in range(n_vehicles)
                for j in out_by_nk.get((p_node, k), [])
            ]
            if terms:
                constraints.append(
                    Constraint(
                        name=f"c1_pickup_{idx}",
                        expression=f"{' + '.join(terms)} + {z_vars[idx]} == 1",
                    )
                )

        # C2: Each served order visited exactly once (delivery)
        for idx in range(n_orders):
            d_node = f"d_{idx}"
            terms = [
                x_vars[(d_node, j, k)]
                for k in range(n_vehicles)
                for j in out_by_nk.get((d_node, k), [])
            ]
            if terms:
                constraints.append(
                    Constraint(
                        name=f"c2_delivery_{idx}",
                        expression=f"{' + '.join(terms)} + {z_vars[idx]} == 1",
                    )
                )

        # C3: Same vehicle serves pickup and delivery
        for idx in range(n_orders):
            p_node = f"p_{idx}"
            d_node = f"d_{idx}"
            for k in range(n_vehicles):
                p_out = [x_vars[(p_node, j, k)] for j in out_by_nk.get((p_node, k), [])]
                d_out = [x_vars[(d_node, j, k)] for j in out_by_nk.get((d_node, k), [])]
                if p_out or d_out:
                    all_terms = [f"{v}" for v in p_out] + [f"-1*{v}" for v in d_out]
                    constraints.append(
                        Constraint(
                            name=f"c3_pair_{idx}_{k}",
                            expression=f"{' + '.join(all_terms)} == 0",
                        )
                    )

        # C4: Flow conservation at customer and rest-stop nodes (in - out = 0)
        for node_id in breakable_nodes:
            for k in range(n_vehicles):
                in_terms = [x_vars[(i, node_id, k)] for i in in_by_nk.get((node_id, k), [])]
                out_terms = [x_vars[(node_id, j, k)] for j in out_by_nk.get((node_id, k), [])]
                if in_terms or out_terms:
                    all_terms = [f"{v}" for v in in_terms] + [f"-1*{v}" for v in out_terms]
                    constraints.append(
                        Constraint(
                            name=f"c4_flow_{node_id}_{k}",
                            expression=f"{' + '.join(all_terms)} == 0",
                        )
                    )

        # C5: Vehicle departs from its origin
        for k in range(n_vehicles):
            o_node = f"o_{k}"
            terms = [x_vars[(o_node, j, k)] for j in out_by_nk.get((o_node, k), [])]
            if terms:
                constraints.append(
                    Constraint(
                        name=f"c5_depart_{k}",
                        expression=(f"{' + '.join(terms)} + -1*{y_vars[k]} == 0"),
                    )
                )

        # C6: Vehicle arrives at its endpoint
        for k in range(n_vehicles):
            e_node = f"e_{k}"
            terms = [x_vars[(i, e_node, k)] for i in in_by_nk.get((e_node, k), [])]
            if terms:
                constraints.append(
                    Constraint(
                        name=f"c6_arrive_{k}",
                        expression=(f"{' + '.join(terms)} + -1*{y_vars[k]} == 0"),
                    )
                )

        # C8: Precedence — per-arc big-M for tighter relaxation
        for idx in range(n_orders):
            p_node = f"p_{idx}"
            d_node = f"d_{idx}"
            t_pd = arc_time.get((p_node, d_node), 0)
            s_p = nodes[p_node].get("service_time", 0)
            # big-M for precedence: based on pickup→delivery arc
            m_prec = arc_big_m.get((p_node, d_node), big_m_global)
            for k in range(n_vehicles):
                if (p_node, k) not in s_vars or (d_node, k) not in s_vars:
                    continue
                p_out = [x_vars[(p_node, j, k)] for j in out_by_nk.get((p_node, k), [])]
                if not p_out:
                    continue
                m_terms = " + ".join(f"{m_prec}*{v}" for v in p_out)
                constraints.append(
                    Constraint(
                        name=f"c8_prec_{idx}_{k}",
                        expression=(
                            f"{s_vars[(p_node, k)]} + {s_p + t_pd}"
                            f" + -1*{s_vars[(d_node, k)]}"
                            f" + {m_terms} <= {m_prec}"
                        ),
                    )
                )

        # C10: Load propagation (MTZ-style) — only on customer-to-customer arcs
        # If X_ijk=1: L_jk = L_ik + q_j
        # L_ik + q_j - M_load*(1-X) <= L_jk  AND  L_ik + q_j + M_load*(1-X) >= L_jk
        for i, j, k in valid_arcs:
            if i not in customer_nodes or j not in customer_nodes:
                continue
            if (i, j, k) not in x_vars:
                continue
            if (i, k) not in l_vars or (j, k) not in l_vars:
                continue
            q_j = nodes[j].get("pallets", 0)
            # Lower: L_ik + q_j - M_load + M_load*X <= L_jk
            # => L_ik + q_j + M_load*X - L_jk <= M_load
            constraints.append(
                Constraint(
                    name=f"c10a_load_{i}_{j}_{k}",
                    expression=(
                        f"{l_vars[(i, k)]} + {q_j}"
                        f" + {m_load}*{x_vars[(i, j, k)]}"
                        f" + -1*{l_vars[(j, k)]} <= {m_load}"
                    ),
                )
            )
            # Upper: L_ik + q_j + M_load - M_load*X >= L_jk
            # => L_ik + q_j - M_load*X - L_jk >= -M_load
            constraints.append(
                Constraint(
                    name=f"c10b_load_{i}_{j}_{k}",
                    expression=(
                        f"{l_vars[(i, k)]} + {q_j}"
                        f" + -1*{m_load}*{x_vars[(i, j, k)]}"
                        f" + -1*{l_vars[(j, k)]} >= -{m_load}"
                    ),
                )
            )

        # C13: Max distance per vehicle
        node_ids = list(nodes.keys())
        for k in range(n_vehicles):
            max_d = safe_float(
                tractors[k].get("max_distance", max_dist_default)
                if k < len(tractors)
                else max_dist_default,
                "max_distance",
            )
            dist_terms = []
            for i_node in node_ids:
                for j_node in out_by_nk.get((i_node, k), []):
                    d = arc_dist.get((i_node, j_node), 0)
                    if d > 0:
                        dist_terms.append(f"{d}*{x_vars[(i_node, j_node, k)]}")
            if dist_terms:
                constraints.append(
                    Constraint(
                        name=f"c13_maxdist_{k}",
                        expression=f"{' + '.join(dist_terms)} <= {max_d}",
                    )
                )

        # C14/C22: Time propagation — per-arc big-M (P2)
        # S_ik + s_i + t_ij - M_ij*(1-X_ijk) <= S_jk
        # => S_ik + M_ij*X_ijk - S_jk <= M_ij - s_i - t_ij
        for i, j, k in valid_arcs:
            if (i, j, k) not in x_vars:
                continue
            if (i, k) not in s_vars or (j, k) not in s_vars:
                continue
            t_ij = arc_time.get((i, j), 0)
            s_i = nodes[i].get("service_time", 0)
            m_ij = arc_big_m.get((i, j), big_m_global)
            rhs = m_ij - s_i - t_ij
            time_expr = f"{s_vars[(i, k)]} + {m_ij}*{x_vars[(i, j, k)]} + -1*{s_vars[(j, k)]}"
            if tacho_enabled and i in breakable_nodes and (i, k) in b_vars:
                time_expr += f" + {TACHO_BREAK_DURATION}*{b_vars[(i, k)]}"
            constraints.append(
                Constraint(
                    name=f"c14_time_{i}_{j}_{k}",
                    expression=f"{time_expr} <= {rhs}",
                )
            )

        # C15: Earliest arrival — now enforced by S variable lower bounds (P0/P2)

        # C16: Tardiness definition — one per (node, vehicle)
        # T_i >= S_ik - b_i when vehicle k visits node i
        # Since T_i >= 0 by bound and minimization drives it down,
        # we use: T_i - S_ik + b_i >= 0  (unconditional, safe)
        for node_id in customer_nodes:
            b_i = nodes[node_id].get("latest", m_time)
            if node_id not in t_vars:
                continue
            for k in range(n_vehicles):
                if not in_by_nk.get((node_id, k)):
                    continue  # vehicle k can't reach this node
                constraints.append(
                    Constraint(
                        name=f"c16_tard_{node_id}_{k}",
                        expression=(f"{t_vars[node_id]} + -1*{s_vars[(node_id, k)]} + {b_i} >= 0"),
                    )
                )

        # Tachograph constraints (S3: breaks-at-nodes model)
        if tacho_enabled:
            # C18: Segment accumulation on arcs
            # H_jk >= H_ik + t_ij - M*(1-X_ijk) - M*B_jk
            # => H_jk - H_ik - t_ij - M*X_ijk + M*B_jk >= -M
            # When X=1,B=0: H_j >= H_i + t (accumulates)
            # When X=1,B=1: H_j >= H_i + t - M (non-binding, C19 resets)
            for i, j, k in valid_arcs:
                if (i, j, k) not in x_vars:
                    continue
                if (i, k) not in h_vars or (j, k) not in h_vars:
                    continue
                t_ij = arc_time.get((i, j), 0)
                expr = (
                    f"{h_vars[(j, k)]}"
                    f" + -1*{h_vars[(i, k)]}"
                    f" + -{t_ij}"
                    f" + -1*{m_drive}*{x_vars[(i, j, k)]}"
                )
                if j in breakable_nodes and (j, k) in b_vars:
                    expr += f" + {m_drive}*{b_vars[(j, k)]}"
                constraints.append(
                    Constraint(
                        name=f"c18_seg_{i}_{j}_{k}",
                        expression=f"{expr} >= -{m_drive}",
                    )
                )

            # C19: Segment reset at break nodes (S3 model)
            # H_ik <= T_drive_max * (1 - B_ik)
            # => H_ik + T_drive_max * B_ik <= T_drive_max
            for node_id in breakable_nodes:
                for k in range(n_vehicles):
                    if (node_id, k) in b_vars and (node_id, k) in h_vars:
                        constraints.append(
                            Constraint(
                                name=f"c19_reset_{node_id}_{k}",
                                expression=(
                                    f"{h_vars[(node_id, k)]}"
                                    f" + {TACHO_CONTINUOUS_DRIVE_MAX}"
                                    f"*{b_vars[(node_id, k)]}"
                                    f" <= {TACHO_CONTINUOUS_DRIVE_MAX}"
                                ),
                            )
                        )

            # C20_force: Forced break when next arc would exceed 4.5h
            # H_ik + t_ij <= T_max + M_drive*(1-X_ijk) + M_drive*B_ik
            # => H_ik + t_ij + M_drive*X_ijk - M_drive*B_ik <= T_max + M_drive
            for i, j, k in valid_arcs:
                if (i, j, k) not in x_vars:
                    continue
                if i not in breakable_nodes:
                    continue
                if (i, k) not in h_vars or (i, k) not in b_vars:
                    continue
                t_ij = arc_time.get((i, j), 0)
                rhs = TACHO_CONTINUOUS_DRIVE_MAX + m_drive
                constraints.append(
                    Constraint(
                        name=f"c20f_force_{i}_{j}_{k}",
                        expression=(
                            f"{h_vars[(i, k)]} + {t_ij}"
                            f" + {m_drive}*{x_vars[(i, j, k)]}"
                            f" + -1*{m_drive}*{b_vars[(i, k)]}"
                            f" <= {rhs}"
                        ),
                    )
                )

            # C23: Daily driving accumulation
            # W_jk >= W_ik + t_ij - M_drive*(1-X_ijk)
            # => W_jk - W_ik - t_ij - M_drive*X_ijk >= -M_drive
            for i, j, k in valid_arcs:
                if (i, j, k) not in x_vars:
                    continue
                if (i, k) not in w_vars or (j, k) not in w_vars:
                    continue
                t_ij = arc_time.get((i, j), 0)
                constraints.append(
                    Constraint(
                        name=f"c23_daily_{i}_{j}_{k}",
                        expression=(
                            f"{w_vars[(j, k)]}"
                            f" + -1*{w_vars[(i, k)]}"
                            f" + -{t_ij}"
                            f" + -1*{m_drive}*{x_vars[(i, j, k)]}"
                            f" >= -{m_drive}"
                        ),
                    )
                )

            # C24: Initial driving accumulators = 0 at depot
            for k in range(n_vehicles):
                o_node = f"o_{k}"
                if (o_node, k) in w_vars:
                    constraints.append(
                        Constraint(
                            name=f"c24_winit_{k}",
                            expression=f"{w_vars[(o_node, k)]} == 0",
                        )
                    )
                if (o_node, k) in h_vars:
                    constraints.append(
                        Constraint(
                            name=f"c24_hinit_{k}",
                            expression=f"{h_vars[(o_node, k)]} == 0",
                        )
                    )

            # C25: Daily driving limit (9h or 10h with extension)
            for node_id in nodes:
                for k in range(n_vehicles):
                    if (node_id, k) in w_vars and k in e_vars:
                        constraints.append(
                            Constraint(
                                name=f"c25_dlimit_{node_id}_{k}",
                                expression=(
                                    f"{w_vars[(node_id, k)]}"
                                    f" + -1*{TACHO_DAILY_DRIVE_EXT - TACHO_DAILY_DRIVE_STD}"
                                    f"*{e_vars[k]}"
                                    f" <= {TACHO_DAILY_DRIVE_STD}"
                                ),
                            )
                        )

            # C26: Max 2 extended days per driver per week
            n_drivers = max(len(drivers), 1)
            ext_terms = [e_vars[k] for k in e_vars]
            if ext_terms:
                constraints.append(
                    Constraint(
                        name="c26_ext_limit",
                        expression=(f"{' + '.join(ext_terms)} <= {2 * n_drivers}"),
                    )
                )

        # Vehicle composition constraints (C29-C34)
        if tractors and trailers and drivers:
            for a_vars, n_res, kind in [
                (a_tr, len(tractors), "tractor"),
                (a_tl, len(trailers), "trailer"),
                (a_dr, len(drivers), "driver"),
            ]:
                self._add_composition_constraints(
                    constraints, a_vars, n_res, n_vehicles, y_vars, kind
                )

            # C35: Tractor-trailer compatibility
            for t_idx, tractor in enumerate(tractors):
                for l_idx, trailer in enumerate(trailers):
                    compat_list = trailer.get("compatible_tractors", [])
                    tractor_id = tractor.get("id", f"tr_{t_idx}")
                    if compat_list and tractor_id not in compat_list:
                        for k in range(n_vehicles):
                            if (t_idx, k) in a_tr and (l_idx, k) in a_tl:
                                constraints.append(
                                    Constraint(
                                        name=f"c35_compat_{t_idx}_{l_idx}_{k}",
                                        expression=(
                                            f"{a_tr[(t_idx, k)]} + {a_tl[(l_idx, k)]} <= 1"
                                        ),
                                    )
                                )

            # C36: Driver-tractor compatibility
            for d_idx, driver in enumerate(drivers):
                qual_tractors = driver.get("qualified_tractors", [])
                if not qual_tractors:
                    continue
                for t_idx, tractor in enumerate(tractors):
                    tractor_id = tractor.get("id", f"tr_{t_idx}")
                    if tractor_id not in qual_tractors:
                        for k in range(n_vehicles):
                            if (d_idx, k) in a_dr and (t_idx, k) in a_tr:
                                constraints.append(
                                    Constraint(
                                        name=f"c36_drcompat_{d_idx}_{t_idx}_{k}",
                                        expression=(
                                            f"{a_dr[(d_idx, k)]} + {a_tr[(t_idx, k)]} <= 1"
                                        ),
                                    )
                                )

        # P4: Symmetry breaking — only when no composition (heterogeneous fleet)
        # With composition, vehicles are distinguishable by tractor/trailer/driver
        if not (tractors and trailers and drivers):
            depot_groups: dict[str, list[int]] = defaultdict(list)
            for k in range(n_vehicles):
                loc = nodes.get(f"o_{k}", {}).get("location", "")
                if loc:
                    depot_groups[loc].append(k)
            add_symmetry_breaking(constraints, y_vars, list(depot_groups.values()))

        # Build heuristic warm start (greedy insertion)
        ws = self._build_greedy_warm_start(
            orders,
            nodes,
            n_vehicles,
            n_orders,
            tractors,
            arc_dist,
            arc_time,
            x_vars,
            z_vars,
            y_vars,
            s_vars,
            tacho_enabled,
            m_time,
            alpha,
            gamma,
        )

        return OptimizationProblem(
            name="mdpdp_tw_tachograph",
            description=(
                f"MDPDP-TW-T: {n_orders} orders, {n_vehicles} vehicles"
                f"{', tachograph enabled' if tacho_enabled else ''}"
            ),
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(obj_terms) if obj_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=time_limit, gap_tolerance=0.02),
            heuristic_warm_start=ws,
        )

    @staticmethod
    def _build_greedy_warm_start(
        orders: list[dict[str, Any]],
        nodes: dict[str, dict[str, Any]],
        n_vehicles: int,
        n_orders: int,
        tractors: list[dict[str, Any]],
        arc_dist: dict[tuple[str, str], float],
        arc_time: dict[tuple[str, str], float],
        x_vars: dict[tuple[str, str, int], str],
        z_vars: dict[int, str],
        y_vars: dict[int, str],
        s_vars: dict[tuple[str, int], str],
        tacho_enabled: bool,
        m_time: float,
        alpha: float,
        gamma: float,
    ) -> dict[str, float] | None:
        """Regret-2 insertion warm start.

        Each step: evaluate all unassigned orders, find best/second-best
        insertion for each, insert the one with highest regret first.
        Uses incremental delta cost (O(1) per candidate, not O(R)).
        """
        routes: dict[int, list[str]] = {k: [f"o_{k}", f"e_{k}"] for k in range(n_vehicles)}
        served: set[int] = set()
        unassigned = set(range(n_orders))

        # Per-vehicle fuel cost
        fuel_by_k = {
            k: tractors[k].get("fuel_cost_per_km", 0.35) if k < len(tractors) else 0.35
            for k in range(n_vehicles)
        }
        max_dist_by_k = {
            k: tractors[k].get("max_distance", 9999) if k < len(tractors) else 9999
            for k in range(n_vehicles)
        }

        # Precompute route costs per vehicle (updated after each insertion)
        route_dist: dict[int, float] = dict.fromkeys(range(n_vehicles), 0.0)
        route_drive: dict[int, float] = dict.fromkeys(range(n_vehicles), 0.0)

        def _delta_cost(
            route: list[str],
            k: int,
            p_node: str,
            d_node: str,
            p_pos: int,
            d_pos: int,
        ) -> float | None:
            """Incremental cost of inserting p_node at p_pos, d_node at d_pos."""
            fuel = fuel_by_k[k]
            # Arcs removed
            removed_d = arc_dist.get((route[p_pos - 1], route[p_pos]), 0)
            # Arcs added for pickup insertion
            added_d = arc_dist.get((route[p_pos - 1], p_node), 0) + arc_dist.get(
                (p_node, route[p_pos]), 0
            )
            if d_pos == p_pos + 1:
                # Delivery immediately after pickup — also removes the p_node→route[p_pos] arc
                added_d = (
                    arc_dist.get((route[p_pos - 1], p_node), 0)
                    + arc_dist.get((p_node, d_node), 0)
                    + arc_dist.get((d_node, route[p_pos]), 0)
                )
            else:
                # Also account for delivery insertion
                # After p inserted, the node at d_pos-1 in original is at d_pos in new route
                d_before = route[d_pos - 2] if d_pos > p_pos + 1 else p_node
                d_after = route[d_pos - 1]
                removed_d += arc_dist.get((d_before, d_after), 0)
                added_d += arc_dist.get((d_before, d_node), 0) + arc_dist.get((d_node, d_after), 0)

            delta_dist = added_d - removed_d
            new_total = route_dist[k] + delta_dist
            if new_total > max_dist_by_k[k]:
                return None

            # Simplified tachograph: rough check on total daily driving
            if tacho_enabled:
                if route_drive[k] + delta_dist / 90.0 > TACHO_DAILY_DRIVE_EXT:
                    return None

            return alpha * new_total * fuel

        while unassigned:
            best_regret = -1.0
            best_order = -1
            best_cost_val = float("inf")
            best_insertion: tuple[int, int, int] = (-1, -1, -1)

            for idx in unassigned:
                p_node = f"p_{idx}"
                d_node = f"d_{idx}"
                top1: tuple[float, int, int, int] | None = None
                top2_cost = float("inf")

                for k in range(n_vehicles):
                    route = routes[k]
                    for p_pos in range(1, len(route)):
                        for d_pos in range(p_pos + 1, len(route) + 1):
                            cost = _delta_cost(route, k, p_node, d_node, p_pos, d_pos)
                            if cost is None:
                                continue
                            if top1 is None or cost < top1[0]:
                                top2_cost = top1[0] if top1 else float("inf")
                                top1 = (cost, k, p_pos, d_pos)
                            elif cost < top2_cost:
                                top2_cost = cost

                if top1 is None:
                    continue

                second = top2_cost if top2_cost < float("inf") else top1[0] + gamma
                regret = second - top1[0]

                if regret > best_regret or (regret == best_regret and top1[0] < best_cost_val):
                    best_regret = regret
                    best_order = idx
                    best_cost_val = top1[0]
                    best_insertion = top1[1:]

            if best_order < 0:
                break

            k, p_pos, d_pos = best_insertion
            route = routes[k]
            routes[k] = (
                route[:p_pos]
                + [f"p_{best_order}"]
                + route[p_pos : d_pos - 1]
                + [f"d_{best_order}"]
                + route[d_pos - 1 :]
            )
            new_dist = sum(
                arc_dist.get((routes[k][i], routes[k][i + 1]), 0) for i in range(len(routes[k]) - 1)
            )
            new_drive = sum(
                arc_time.get((routes[k][i], routes[k][i + 1]), 0) for i in range(len(routes[k]) - 1)
            )
            route_dist[k] = new_dist
            route_drive[k] = new_drive
            served.add(best_order)
            unassigned.discard(best_order)

        # Convert to warm start dict
        ws: dict[str, float] = {}
        for k in range(n_vehicles):
            route = routes[k]
            ws[y_vars[k]] = 1.0 if len(route) > 2 else 0.0
            for pos in range(len(route) - 1):
                xv = x_vars.get((route[pos], route[pos + 1], k))
                if xv:
                    ws[xv] = 1.0
            # Forward time simulation
            t = 0.0
            for pos, nid in enumerate(route):
                sv = s_vars.get((nid, k))
                if sv:
                    t = max(t, nodes[nid].get("earliest", 0))
                    ws[sv] = t
                if pos < len(route) - 1:
                    t += nodes[nid].get("service_time", 0) + arc_time.get(
                        (route[pos], route[pos + 1]), 0
                    )

        for idx in range(n_orders):
            zv = z_vars.get(idx)
            if zv:
                ws[zv] = 0.0 if idx in served else 1.0

        return ws if ws else None

    def _build_distance_maps(
        self, dist_data: list[dict[str, Any]]
    ) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
        """Build (from, to) -> distance and (from, to) -> time maps."""
        dist_map: dict[tuple[str, str], float] = {}
        time_map: dict[tuple[str, str], float] = {}
        for entry in dist_data:
            src = self.sanitize_name(str(entry.get("from", entry.get("source", ""))))
            dst = self.sanitize_name(str(entry.get("to", entry.get("target", ""))))
            dist_map[(src, dst)] = float(entry.get("km", entry.get("distance", 0)))
            time_map[(src, dst)] = float(entry.get("hours", entry.get("time", 0)))
        return dist_map, time_map

    def _build_nodes(
        self,
        orders: list[dict[str, Any]],
        tractors: list[dict[str, Any]],
        depots: list[dict[str, Any]],
        n_vehicles: int,
    ) -> dict[str, dict[str, Any]]:
        """Build the node set: origins, pickups, deliveries, endpoints."""
        nodes: dict[str, dict[str, Any]] = {}
        depot_by_id = {dep.get("id"): dep for dep in depots}

        for k in range(n_vehicles):
            depot_loc = ""
            if k < len(tractors):
                depot_id = tractors[k].get("depot", "")
                dep = depot_by_id.get(depot_id)
                if dep:
                    depot_loc = self.sanitize_name(str(dep.get("location", depot_id)))
                if not depot_loc:
                    depot_loc = self.sanitize_name(str(depot_id))

            nodes[f"o_{k}"] = {"type": NT_ORIGIN, "location": depot_loc, "service_time": 0}
            nodes[f"e_{k}"] = {"type": NT_ENDPOINT, "location": depot_loc, "service_time": 0}

        for idx, order in enumerate(orders):
            pickup = order.get("pickup", {})
            delivery = order.get("delivery", {})
            p_loc = self.sanitize_name(str(pickup.get("location", f"ploc_{idx}")))
            d_loc = self.sanitize_name(str(delivery.get("location", f"dloc_{idx}")))
            pallets = safe_float(pickup.get("pallets", order.get("pallets", 1)), "pallets")

            nodes[f"p_{idx}"] = {
                "type": NT_PICKUP,
                "location": p_loc,
                "earliest": safe_float(pickup.get("earliest", 0), "earliest"),
                "latest": safe_float(pickup.get("latest", 24), "latest"),
                "service_time": safe_float(pickup.get("service_time", 0.5), "service_time"),
                "pallets": pallets,
            }
            nodes[f"d_{idx}"] = {
                "type": NT_DELIVERY,
                "location": d_loc,
                "earliest": safe_float(delivery.get("earliest", 0), "earliest"),
                "latest": safe_float(delivery.get("latest", 24), "latest"),
                "service_time": safe_float(delivery.get("service_time", 0.5), "service_time"),
                "pallets": -pallets,
            }
        return nodes

    def _build_valid_arcs(
        self,
        nodes: dict[str, dict[str, Any]],
        n_vehicles: int,
        n_orders: int,
        dist_map: dict[tuple[str, str], float],
        max_dist: float,
        blocked_loc_pairs: set[tuple[str, str]] | None = None,
    ) -> list[tuple[str, str, int]]:
        """Build sparsified arc set — only plausible transitions."""
        blocked = blocked_loc_pairs or set()
        arcs: list[tuple[str, str, int]] = []
        node_ids = list(nodes.keys())

        for k in range(n_vehicles):
            o_k = f"o_{k}"
            e_k = f"e_{k}"

            for i in node_ids:
                i_type = nodes[i]["type"]
                if i_type == NT_ENDPOINT:
                    continue
                if i_type == NT_ORIGIN and i != o_k:
                    continue

                for j in node_ids:
                    if i == j:
                        continue
                    j_type = nodes[j]["type"]
                    if j_type == NT_ORIGIN:
                        continue
                    if j_type == NT_ENDPOINT and j != e_k:
                        continue
                    if i_type == NT_ORIGIN and j_type not in (
                        NT_PICKUP,
                        NT_REST_STOP,
                        NT_ENDPOINT,
                    ):
                        continue
                    if i_type == NT_DELIVERY and j_type == NT_PICKUP:
                        i_order = int(i.split("_")[1])
                        j_order = int(j.split("_")[1])
                        if i_order == j_order:
                            continue

                    loc_i = nodes[i].get("location", "")
                    loc_j = nodes[j].get("location", "")

                    if (loc_i, loc_j) in blocked:
                        continue
                    if (i_type == NT_REST_STOP or j_type == NT_REST_STOP) and (
                        loc_i,
                        loc_j,
                    ) not in dist_map:
                        continue

                    d = dist_map.get((loc_i, loc_j), dist_map.get((i, j), 0))
                    if (
                        d > max_dist * ARC_DISTANCE_THRESHOLD
                        and i_type != NT_ORIGIN
                        and j_type != NT_ENDPOINT
                    ):
                        continue

                    arcs.append((i, j, k))

        return arcs

    @staticmethod
    def _filter_vehicle_order_arcs(
        valid_arcs: list[tuple[str, str, int]],
        nodes: dict[str, dict[str, Any]],
        n_vehicles: int,
        n_orders: int,
        time_map: dict[tuple[str, str], float],
        max_tardiness: float = 4.0,
    ) -> list[tuple[str, str, int]]:
        """Remove arcs for (vehicle, order) pairs that are time-infeasible.

        If vehicle k cannot reach order i's pickup from its depot within
        the time window (+ max_tardiness slack), remove all arcs connecting
        vehicle k to that order's pickup and delivery nodes.
        """
        infeasible: set[tuple[int, int]] = set()
        for k in range(n_vehicles):
            depot_loc = nodes.get(f"o_{k}", {}).get("location", "")
            for idx in range(n_orders):
                pickup_loc = nodes.get(f"p_{idx}", {}).get("location", "")
                # Same location = 0 travel; unknown = inf (infeasible)
                if depot_loc == pickup_loc:
                    travel = 0.0
                else:
                    travel = time_map.get((depot_loc, pickup_loc), float("inf"))
                latest = nodes.get(f"p_{idx}", {}).get("latest", 24)
                if travel > latest + max_tardiness:
                    infeasible.add((k, idx))

        if not infeasible:
            return valid_arcs

        def _order_of(node_id: str) -> int | None:
            if node_id.startswith(("p_", "d_")):
                parts = node_id.split("_")
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
            return None  # non-order nodes (depots, rest stops) are never filtered

        return [
            (i, j, k)
            for i, j, k in valid_arcs
            if ((oi := _order_of(i)) is None or (k, oi) not in infeasible)
            and ((oj := _order_of(j)) is None or (k, oj) not in infeasible)
        ]

    @staticmethod
    def _add_composition_constraints(
        constraints: list[Constraint],
        a_vars: dict[tuple[int, int], str],
        n_resources: int,
        n_vehicles: int,
        y_vars: dict[int, str],
        kind: str,
    ) -> None:
        """Add assignment + uniqueness constraints for one resource type."""
        # Each used vehicle gets exactly one resource
        for k in range(n_vehicles):
            terms = [a_vars[(r, k)] for r in range(n_resources) if (r, k) in a_vars]
            if terms:
                constraints.append(
                    Constraint(
                        name=f"c_assign_{kind}_{k}",
                        expression=f"{' + '.join(terms)} + -1*{y_vars[k]} == 0",
                    )
                )
        # Each resource assigned to at most one vehicle
        for r in range(n_resources):
            terms = [a_vars[(r, k)] for k in range(n_vehicles) if (r, k) in a_vars]
            if terms:
                constraints.append(
                    Constraint(
                        name=f"c_uniq_{kind}_{r}",
                        expression=f"{' + '.join(terms)} <= 1",
                    )
                )

    def _insert_rest_stops(
        self,
        dist_map: dict[tuple[str, str], float],
        time_map: dict[tuple[str, str], float],
        threshold: float = REST_STOP_THRESHOLD,
        active_locations: set[str] | None = None,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[tuple[str, str], float],
        dict[tuple[str, str], float],
        set[tuple[str, str]],
    ]:
        """Insert virtual rest-stop nodes on arcs exceeding the driving threshold.

        Only processes location pairs where both endpoints are in active_locations
        (order pickup/delivery locations and depot locations). This prevents
        creating rest stops for irrelevant city pairs.

        Returns (new_nodes, updated_dist_map, updated_time_map, blocked_pairs).
        blocked_pairs are the original long (loc_a, loc_b) pairs whose direct
        arcs should be blocked — vehicles must use the rest-stop chain instead.
        """
        new_nodes: dict[str, dict[str, Any]] = {}
        new_dist: dict[tuple[str, str], float] | None = None
        new_time: dict[tuple[str, str], float] | None = None
        blocked: set[tuple[str, str]] = set()

        for (loc_a, loc_b), t_ab in list(time_map.items()):
            if t_ab <= threshold:
                continue
            if active_locations and (
                loc_a not in active_locations or loc_b not in active_locations
            ):
                continue

            # Lazy copy — only when first long arc is found
            if new_dist is None:
                new_dist = dict(dist_map)
                new_time = dict(time_map)

            d_ab = dist_map.get((loc_a, loc_b), 0)
            n_segments = math.ceil(t_ab / threshold)
            seg_time = round(t_ab / n_segments, 4)
            seg_dist = round(d_ab / n_segments, 2)

            blocked.add((loc_a, loc_b))

            prev_loc = loc_a
            for s in range(1, n_segments):
                rst_loc = f"rst_{loc_a}_{loc_b}_{s}"
                new_nodes[rst_loc] = {
                    "type": NT_REST_STOP,
                    "location": rst_loc,
                    "service_time": 0,
                    "earliest": 0,
                    "latest": REST_STOP_HORIZON,
                }
                new_dist[(prev_loc, rst_loc)] = seg_dist
                new_time[(prev_loc, rst_loc)] = seg_time
                new_dist[(rst_loc, prev_loc)] = seg_dist
                new_time[(rst_loc, prev_loc)] = seg_time
                prev_loc = rst_loc

            new_dist[(prev_loc, loc_b)] = seg_dist
            new_time[(prev_loc, loc_b)] = seg_time
            new_dist[(loc_b, prev_loc)] = seg_dist
            new_time[(loc_b, prev_loc)] = seg_time

        return new_nodes, new_dist or dist_map, new_time or time_map, blocked
