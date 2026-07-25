"""The graph a solved model describes — recovery, layering and refusal.

Two things matter more than the drawing: that a graph is only offered when one
genuinely exists, and that nothing about node POSITION is invented. Models carry
distances, not coordinates, so layers are derived from the edges and nothing else.
"""

import pytest

from app.domains.solver.services.solution_graph import MAX_EDGES, build_solution_graph
from app.schemas.optimization import (
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)

pytestmark = pytest.mark.unit


def _problem(
    specs: list[tuple[str, str, list[str]]],
    vtype: VariableType = VariableType.BINARY,
) -> OptimizationProblem:
    """Build a problem from ``(name, family, index_tuple)`` triples."""
    variables = [
        Variable(name=name, type=vtype, family=family, index_tuple=idx)
        for name, family, idx in specs
    ]
    return OptimizationProblem(
        variables=variables,
        objective=Objective(
            sense=ObjectiveSense.MINIMIZE,
            expression=" + ".join(v.name for v in variables),
        ),
    )


class TestRecovery:
    def test_three_arc_layers_become_one_chain_per_group(self):
        """The TFM shape: start->load, load->unload, unload->end, one per vehicle.

        Index tuples arrive the way the compiler stamps a 3-dimensional tuple
        set — ONE entry holding three components joined with "_".
        """
        problem = _problem(
            [
                ("xsc_s2_c2_k2", "xsc", ["s2_c2_k2"]),
                ("xcd_c2_d2_k2", "xcd", ["c2_d2_k2"]),
                ("xde_d2_e2_k2", "xde", ["d2_e2_k2"]),
                ("xsc_s3_c3_k3", "xsc", ["s3_c3_k3"]),
                ("xsc_s1_c1_k1", "xsc", ["s1_c1_k1"]),  # candidate, not chosen
            ]
        )
        solution = {
            "xsc_s2_c2_k2": 1.0,
            "xcd_c2_d2_k2": 1.0,
            "xde_d2_e2_k2": 1.0,
            "xsc_s3_c3_k3": 1.0,
            "xsc_s1_c1_k1": 0.0,
        }
        graph = build_solution_graph(problem, solution)

        assert graph is not None
        assert graph.active_count == 4
        assert graph.candidate_count == 5  # the honest "4 active of 5"
        assert sorted(graph.groups) == ["k2", "k3"]
        # The chain is laid out by flow position, not by any invented geometry.
        assert graph.layers["s2"] == 0
        assert graph.layers["c2"] == 1
        assert graph.layers["d2"] == 2
        assert graph.layers["e2"] == 3
        # Shared labels between the two sides — this is a network, not a matching.
        assert graph.is_network is True

    def test_reads_labels_that_contain_underscores(self):
        """Flat routing names give ``["o_0", "p_1", "2"]`` — three components.

        Two arcs, so the family's own dimensions overlap and it reads as the
        network it is (a lone arc is indistinguishable from an attribute).
        """
        specs = [
            ("x_o_0_p_1_2", "x", ["o_0", "p_1", "2"]),
            ("x_p_1_e_0_2", "x", ["p_1", "e_0", "2"]),
        ]
        graph = build_solution_graph(_problem(specs), {n: 1.0 for n, _, _ in specs})

        assert graph is not None
        edge = next(e for e in graph.edges if e.variable == "x_o_0_p_1_2")
        assert (edge.source, edge.target, edge.group) == ("o_0", "p_1", "2")

    def test_bipartite_assignment_is_not_a_network(self):
        problem = _problem(
            [
                ("assign_w1_t1", "assign", ["w1", "t1"]),
                ("assign_w2_t2", "assign", ["w2", "t2"]),
            ]
        )
        graph = build_solution_graph(problem, {"assign_w1_t1": 1.0, "assign_w2_t2": 1.0})

        assert graph is not None
        assert graph.is_network is False
        # No third component, so no group to colour by.
        assert graph.groups == []
        assert all(e.group is None for e in graph.edges)
        assert graph.layers == {"w1": 0, "w2": 0, "t1": 1, "t2": 1}


class TestEdgeFamilySelection:
    """Being indexed by two labels does not make a variable an edge.

    A routing model is full of counter-examples, and drawing them produced a
    picture with "p0 -> 0" arrows in it — the index tuple read out loud rather
    than a route.
    """

    # CONTRACT-TEST: an attribute indexed by (node, resource) — an arrival time,
    # a load — must never be drawn as an edge from the node to the resource.
    def test_per_node_attributes_are_not_drawn_as_edges(self):
        specs = [
            # Real arcs: the two leading dimensions range over the same nodes.
            ("x_o0_p0_0", "x", ["o0", "p0", "0"]),
            ("x_p0_d0_0", "x", ["p0", "d0", "0"]),
            ("x_d0_e0_0", "x", ["d0", "e0", "0"]),
        ]
        # Arrival times over (node, vehicle) — continuous, and its second
        # dimension is a vehicle, not a node.
        attrs = [("s_o0_0", "s", ["o0", "0"]), ("s_p0_0", "s", ["p0", "0"])]

        variables = [
            Variable(name=n, type=VariableType.BINARY, family=f, index_tuple=i) for n, f, i in specs
        ] + [
            Variable(name=n, type=VariableType.CONTINUOUS, family=f, index_tuple=i)
            for n, f, i in attrs
        ]
        problem = OptimizationProblem(
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(v.name for v in variables),
            ),
        )
        solution = {n: 1.0 for n, _, _ in specs} | {"s_o0_0": 3.5, "s_p0_0": 9.0}

        graph = build_solution_graph(problem, solution)
        assert graph is not None
        assert graph.families == ["x"]
        assert all(e.family == "x" for e in graph.edges)
        # The vehicle label must not have become a node.
        assert "0" not in graph.nodes

    # The TFM formulation writes a path as three SEPARATE families, none of
    # which is self-network — they are one graph because each hands off to the
    # next. Chaining must find them.
    def test_chained_arc_layers_are_drawn_as_one_graph(self):
        specs = [
            ("xsc_s1_c1_k1", "xsc", ["s1_c1_k1"]),
            ("xcd_c1_d1_k1", "xcd", ["c1_d1_k1"]),
            ("xde_d1_e1_k1", "xde", ["d1_e1_k1"]),
        ]
        graph = build_solution_graph(_problem(specs), {n: 1.0 for n, _, _ in specs})
        assert graph is not None
        assert sorted(graph.families) == ["xcd", "xde", "xsc"]

    def test_the_busiest_unrelated_relation_wins(self):
        """Two unrelated relations overlaid say nothing true about either."""
        arcs = [
            ("x_a1_b1", "x", ["a1", "b1"]),
            ("x_b1_c1", "x", ["b1", "c1"]),
            ("x_c1_a1", "x", ["c1", "a1"]),
        ]
        other = [("m_w1_t1", "m", ["w1", "t1"])]
        specs = arcs + other
        graph = build_solution_graph(_problem(specs), {n: 1.0 for n, _, _ in specs})
        assert graph is not None
        assert graph.families == ["x"]

    # A continuous flow over (node, node) IS an edge — the self-network signal
    # is strong enough on its own, so the discrete requirement must not apply.
    def test_a_continuous_flow_between_nodes_is_still_a_graph(self):
        specs = [("f_a1_b1", "f", ["a1", "b1"]), ("f_b1_a1", "f", ["b1", "a1"])]
        graph = build_solution_graph(
            _problem(specs, vtype=VariableType.CONTINUOUS), {"f_a1_b1": 12.5, "f_b1_a1": 0.0}
        )
        assert graph is not None
        assert graph.families == ["f"]

    # A bipartite matching is neither self-network nor chained, so it is only
    # admitted as a fallback — and only when binary.
    def test_a_binary_matching_is_admitted_on_its_own(self):
        specs = [("assign_w1_t1", "assign", ["w1", "t1"])]
        graph = build_solution_graph(_problem(specs), {"assign_w1_t1": 1.0})
        assert graph is not None
        assert graph.families == ["assign"]

    def test_a_continuous_two_index_attribute_alone_is_not_a_graph(self):
        specs = [("cost_w1_t1", "cost", ["w1", "t1"])]
        graph = build_solution_graph(
            _problem(specs, vtype=VariableType.CONTINUOUS), {"cost_w1_t1": 42.0}
        )
        assert graph is None


# CONTRACT-TEST: the real generator, not a hand-written fixture. A synthetic
# problem only contains the families the test author thought of; the actual MDPDP
# generator emits arrival times, loads, break flags and resource assignments
# alongside the arcs — which is how the "p0 -> 0" bug got in and why the fixture
# suite did not catch it.
def test_a_real_generated_routing_model_draws_only_its_arcs():
    from app.domains.solver.services.generators import get_generator
    from app.schemas.solution_structure import annotate_variable_structure

    problem = get_generator("mdpdp").generate(
        {
            "orders": [
                {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5},
                {"pickup": {"location": "MAD"}, "delivery": {"location": "VLC"}, "pallets": 4},
            ],
            "tractors": [
                {"id": "tr1", "depot": "dep1", "fuel_cost_per_km": 0.35, "max_distance": 2000}
            ],
            "trailers": [{"id": "tl1", "capacity_pallets": 33}],
            "drivers": [{"id": "dr1"}],
            "depots": [{"id": "dep1", "location": "BCN"}],
            "distances": [
                {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
                {"from": "MAD", "to": "VLC", "km": 360, "hours": 3.6},
                {"from": "VLC", "to": "MAD", "km": 360, "hours": 3.6},
                {"from": "BCN", "to": "VLC", "km": 350, "hours": 3.5},
                {"from": "VLC", "to": "BCN", "km": 350, "hours": 3.5},
            ],
            "config": {"tachograph_enabled": False, "time_limit_seconds": 20},
        },
        {},
    )
    annotate_variable_structure(problem)

    # The generator emits far more than arcs — prove the fixture is realistic
    # before asserting on what survives.
    emitted = {v.family for v in problem.variables if v.family}
    assert {"x", "s", "l"} <= emitted, f"generator no longer emits the mix under test: {emitted}"

    # Activate one arc plus non-zero arrival times, the shape of a real solution.
    solution: dict[str, float] = {}
    for var in problem.variables:
        if var.family == "x":
            solution[var.name] = 0.0
        elif var.family in ("s", "l"):
            solution[var.name] = 4.0
    first_arc = next(v.name for v in problem.variables if v.family == "x")
    solution[first_arc] = 1.0

    graph = build_solution_graph(problem, solution)
    assert graph is not None
    assert graph.families == ["x"], f"non-arc families leaked into the graph: {graph.families}"
    assert graph.active_count == 1


class TestRefusal:
    """Declining is a feature: an empty frame is worse than no frame."""

    def test_no_multi_index_family_returns_none(self):
        problem = _problem([("x_1", "x", ["1"]), ("x_2", "x", ["2"])])
        assert build_solution_graph(problem, {"x_1": 1.0, "x_2": 1.0}) is None

    def test_unstructured_variables_return_none(self):
        problem = OptimizationProblem(
            variables=[Variable(name="total_cost", type=VariableType.CONTINUOUS)],
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="total_cost"),
        )
        assert build_solution_graph(problem, {"total_cost": 5.0}) is None

    def test_solution_activating_nothing_returns_none(self):
        problem = _problem([("assign_w1_t1", "assign", ["w1", "t1"])])
        assert build_solution_graph(problem, {"assign_w1_t1": 0.0}) is None

    def test_missing_solution_returns_none(self):
        problem = _problem([("assign_w1_t1", "assign", ["w1", "t1"])])
        assert build_solution_graph(problem, None) is None
        assert build_solution_graph(problem, {}) is None

    # CONTRACT-TEST: a family whose members disagree on arity is a parse we must
    # not trust — its edges would not all mean the same thing.
    def test_family_with_inconsistent_arity_is_skipped(self):
        problem = _problem(
            [
                ("x_a1_b1", "x", ["a1", "b1"]),
                ("x_a1_b1_c1", "x", ["a1", "b1", "c1"]),
            ]
        )
        assert build_solution_graph(problem, {"x_a1_b1": 1.0, "x_a1_b1_c1": 1.0}) is None


class TestThresholds:
    def test_binary_at_solver_noise_still_counts_as_active(self):
        """A binary at 1 comes back from a MIP as 0.9999999997."""
        problem = _problem([("assign_w1_t1", "assign", ["w1", "t1"])])
        graph = build_solution_graph(problem, {"assign_w1_t1": 0.9999999997})
        assert graph is not None and graph.active_count == 1

    def test_binary_at_solver_noise_near_zero_is_not_an_edge(self):
        problem = _problem([("assign_w1_t1", "assign", ["w1", "t1"])])
        assert build_solution_graph(problem, {"assign_w1_t1": 1e-9}) is None

    def test_continuous_flow_uses_a_nonzero_threshold_not_a_half(self):
        """A flow of 0.2 is a real shipment; 0.5 is a binary convention, not a flow."""
        problem = _problem(
            [("flow_a1_b1", "flow", ["a1", "b1"]), ("flow_b1_c1", "flow", ["b1", "c1"])],
            vtype=VariableType.CONTINUOUS,
        )
        graph = build_solution_graph(problem, {"flow_a1_b1": 0.2, "flow_b1_c1": 0.0})
        assert graph is not None
        assert [e.value for e in graph.edges] == [0.2]


class TestSizeAndCycles:
    def test_beyond_the_cap_it_truncates_and_says_so(self):
        specs = [(f"a_x{i}_y{i}", "a", [f"x{i}", f"y{i}"]) for i in range(MAX_EDGES + 25)]
        problem = _problem(specs)
        graph = build_solution_graph(problem, {name: 1.0 for name, _, _ in specs})

        assert graph is not None
        assert graph.truncated is True
        assert len(graph.edges) == MAX_EDGES
        # The count reported is the REAL one, not the drawn one — otherwise
        # truncation would read as a smaller problem.
        assert graph.active_count == MAX_EDGES + 25

    # A tour that returns to its depot has no layering at all. Layering must
    # degrade to something readable instead of looping forever.
    def test_a_cycle_terminates_and_still_lays_out(self):
        specs = [
            ("t_a1_b1", "t", ["a1", "b1"]),
            ("t_b1_c1", "t", ["b1", "c1"]),
            ("t_c1_a1", "t", ["c1", "a1"]),
        ]
        graph = build_solution_graph(_problem(specs), {name: 1.0 for name, _, _ in specs})

        assert graph is not None
        assert set(graph.nodes) == {"a1", "b1", "c1"}
        assert all(isinstance(d, int) for d in graph.layers.values())

    def test_a_self_loop_does_not_deepen_forever(self):
        problem = _problem([("t_a1_a1", "t", ["a1", "a1"])])
        graph = build_solution_graph(problem, {"t_a1_a1": 1.0})
        assert graph is not None
        assert graph.layers == {"a1": 0}
