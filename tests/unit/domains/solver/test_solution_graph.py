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
        """Flat routing names give ``["o_0", "p_1", "2"]`` — three components."""
        problem = _problem([("x_o_0_p_1_2", "x", ["o_0", "p_1", "2"])])
        graph = build_solution_graph(problem, {"x_o_0_p_1_2": 1.0})

        assert graph is not None
        edge = graph.edges[0]
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
        problem = _problem([("flow_a1_b1", "flow", ["a1", "b1"])], vtype=VariableType.CONTINUOUS)
        graph = build_solution_graph(problem, {"flow_a1_b1": 0.2})
        assert graph is not None
        assert graph.edges[0].value == 0.2


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
