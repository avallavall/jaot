"""Covering generator — set-covering and set-partitioning problems.

Supports domain-specific input formats (flight crew pairings, emergency
stations/zones, etc.) by auto-detecting sets and coverage data.
"""

from typing import Any

from app.domains.solver.services.generators.base import BaseGenerator, find_list_field
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)


class CoveringGenerator(BaseGenerator):
    """Generate set-covering/partitioning problems.

    Each set covers some elements; minimize cost to cover all elements.

    Params:
        mode: "cover" (>= 1, default) or "partition" (== 1)
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        sets = find_list_field(
            user_input,
            [
                "sets",
                "candidate_pairings",
                "stations",
                "options",
            ],
        )
        num_elements = user_input.get("num_elements", 0)
        mode = params.get("mode", "cover")

        # Auto-detect elements from secondary list
        elements = find_list_field(
            user_input,
            [
                "elements",
                "flight_legs",
                "zones",
                "demands",
            ],
        )

        # Coverage matrix: can be list-of-lists (2D) or list-of-dicts (sparse)
        coverage_matrix_raw = user_input.get("coverage_matrix")
        coverage_matrix: list[list[int]] | None = None
        sparse_coverage: dict[str, set[str]] | None = None

        if coverage_matrix_raw and isinstance(coverage_matrix_raw, list):
            if coverage_matrix_raw and isinstance(coverage_matrix_raw[0], dict):
                # Sparse format: [{station: X, zone: Y, ...}, ...]
                sparse_coverage = {}
                for entry in coverage_matrix_raw:
                    set_name = (
                        entry.get("station") or entry.get("set") or entry.get("pairing") or ""
                    )
                    elem_name = entry.get("zone") or entry.get("element") or entry.get("leg") or ""
                    if set_name and elem_name:
                        sparse_coverage.setdefault(set_name, set()).add(elem_name)
            elif coverage_matrix_raw and isinstance(coverage_matrix_raw[0], list):
                coverage_matrix = coverage_matrix_raw

        if not sets:
            raise ValueError(
                f"Covering generator requires sets/options. Got keys: {list(user_input.keys())}"
            )

        # Determine num_elements from elements list or coverage matrix
        if elements and not num_elements:
            num_elements = len(elements)
        elif coverage_matrix and not num_elements:
            num_elements = len(coverage_matrix[0]) if coverage_matrix else 0
        elif not num_elements and sets:
            # Try to infer from covers lists
            all_covered: set[int] = set()
            for s in sets:
                for c in s.get("covers", []):
                    all_covered.add(c)
            if all_covered:
                num_elements = max(all_covered) + 1

        variables: list[Variable] = []
        cost_terms: list[str] = []

        for i, s in enumerate(sets):
            s_name = self.sanitize_name(s.get("name", f"set_{i}"))
            cost = s.get("cost", 1)
            variables.append(Variable(name=s_name, type=VariableType.BINARY))
            cost_terms.append(f"{cost}*{s_name}")

        constraints: list[Constraint] = []
        op = "== 1" if mode == "partition" else ">= 1"

        if sparse_coverage:
            elem_names_set: set[str] = set()
            for covered in sparse_coverage.values():
                elem_names_set.update(covered)
            for elem_raw in sorted(elem_names_set):
                covering_vars = []
                for i, s in enumerate(sets):
                    s_raw_name = s.get("name", f"set_{i}")
                    s_name = self.sanitize_name(s_raw_name)
                    if s_raw_name in sparse_coverage and elem_raw in sparse_coverage[s_raw_name]:
                        covering_vars.append(s_name)
                if covering_vars:
                    constraints.append(
                        Constraint(
                            name=f"cover_{self.sanitize_name(elem_raw)}",
                            expression=f"{' + '.join(covering_vars)} {op}",
                        )
                    )
        else:
            for e in range(num_elements):
                covering_vars = []

                if coverage_matrix:
                    for i, s in enumerate(sets):
                        s_name = self.sanitize_name(s.get("name", f"set_{i}"))
                        if i < len(coverage_matrix) and e < len(coverage_matrix[i]):
                            if coverage_matrix[i][e]:
                                covering_vars.append(s_name)
                else:
                    for i, s in enumerate(sets):
                        s_name = self.sanitize_name(s.get("name", f"set_{i}"))
                        covers = s.get("covers", s.get("legs_covered", []))
                        if e in covers:
                            covering_vars.append(s_name)

                if covering_vars:
                    elem_name = (
                        self.sanitize_name(elements[e].get("name", f"e_{e}"))
                        if elements and e < len(elements) and isinstance(elements[e], dict)
                        else str(e)
                    )
                    constraints.append(
                        Constraint(
                            name=f"cover_{elem_name}",
                            expression=f"{' + '.join(covering_vars)} {op}",
                        )
                    )

        return OptimizationProblem(
            name="covering",
            description=f"Cover {num_elements} elements with minimum cost from {len(sets)} sets",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
