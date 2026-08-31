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

#: Where a set states what it costs. A covering card whose sets carry
#: "fixed_cost" or "cost_per_unit" is not a card without costs.
_COST_KEYS = ("cost", "fixed_cost", "cost_per_unit", "opening_cost", "price")


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
                "candidate_sites",
                "stations",
                "options",
            ],
            fallback=False,
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
                "demand_zones",
                "communities",
                "demands",
            ],
            fallback=False,
        )

        # Coverage matrix: can be list-of-lists (2D) or list-of-dicts (sparse)
        coverage_matrix_raw = user_input.get("coverage_matrix")
        coverage_matrix: list[list[int]] | None = None
        sparse_coverage: dict[str, set[str]] | None = None

        # Three shapes reach this field. A dense 0/1 grid, a list of
        # {station, zone} dicts, and a list of [set_index, element_index]
        # pairs. The pair list used to be read as a dense grid, which turned
        # "site 0 covers zone 0" into "site 0 covers nothing", so a card could
        # not state its coverage at all.
        if params.get("coverage_format") == "index_pairs":
            pairs: dict[int, set[int]] = {}
            for entry in coverage_matrix_raw or []:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    raise ValueError(
                        f"coverage_format 'index_pairs' needs [set, element] rows, got {entry!r}"
                    )
                pairs.setdefault(int(entry[0]), set()).add(int(entry[1]))
            width = max((max(v) for v in pairs.values() if v), default=-1) + 1
            coverage_matrix = [
                [1 if e in pairs.get(i, set()) else 0 for e in range(width)]
                for i in range(len(sets))
            ]
            coverage_matrix_raw = None

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

        # Two sets that sanitize alike become one binary, so the cheaper of the
        # two is picked for both and one option leaves the model unnoticed.
        self.reject_name_collisions(
            [self.sanitize_name(s.get("name", f"set_{i}")) for i, s in enumerate(sets)],
            [s.get("name") for s in sets],
            "Sets",
        )

        for i, s in enumerate(sets):
            s_name = self.sanitize_name(s.get("name", f"set_{i}"))
            # A missing cost used to become 1, which turns "cheapest cover"
            # into "fewest sets" — a different answer that still looks optimal.
            cost = next(
                (float(s[key]) for key in _COST_KEYS if s.get(key) is not None),
                None,
            )
            if cost is None:
                raise ValueError(
                    f"Set '{s.get('name', i)}' states no cost. "
                    f"Expected one of: {', '.join(_COST_KEYS)}."
                )
            variables.append(Variable(name=s_name, type=VariableType.BINARY))
            cost_terms.append(f"{cost}*{s_name}")

        constraints: list[Constraint] = []
        op = "== 1" if mode == "partition" else ">= 1"

        uncoverable: list[str] = []

        if sparse_coverage:
            elem_names_set: set[str] = set()
            for covered in sparse_coverage.values():
                elem_names_set.update(covered)
            # An element the card declares but no coverage row mentions belongs
            # in the universe too. Taking the universe from the coverage rows
            # alone gave such an element no row at all, and the solve came back
            # optimal with that zone covered by nobody. The dense branch has
            # refused this since the release; the sparse branch did not.
            for el in elements:
                if isinstance(el, dict) and el.get("name"):
                    elem_names_set.add(str(el["name"]))
            for elem_raw in sorted(elem_names_set):
                covering_vars = []
                for i, s in enumerate(sets):
                    s_raw_name = s.get("name", f"set_{i}")
                    s_name = self.sanitize_name(s_raw_name)
                    if s_raw_name in sparse_coverage and elem_raw in sparse_coverage[s_raw_name]:
                        covering_vars.append(s_name)
                # Same rule as the dense branch: an element may ask to be
                # covered more than once.
                need = next(
                    (
                        el.get("min_coverage", el.get("required_coverage"))
                        for el in elements
                        if isinstance(el, dict) and str(el.get("name", "")) == elem_raw
                    ),
                    None,
                )
                row_op = f">= {float(need)}" if need is not None and mode != "partition" else op
                if covering_vars:
                    constraints.append(
                        Constraint(
                            name=f"cover_{self.sanitize_name(elem_raw)}",
                            expression=f"{' + '.join(covering_vars)} {row_op}",
                        )
                    )
                else:
                    uncoverable.append(elem_raw)

            if uncoverable:
                raise ValueError(
                    f"No set covers element(s): {', '.join(uncoverable)}. "
                    "Every element must appear in at least one set's coverage."
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

                elem_name = (
                    self.sanitize_name(elements[e].get("name", f"e_{e}"))
                    if elements and e < len(elements) and isinstance(elements[e], dict)
                    else str(e)
                )
                # An element may need covering more than once. A city centre
                # asking for two stations within reach got the same ">= 1" as
                # everywhere else, so min_coverage never reached the model.
                need = None
                if elements and e < len(elements) and isinstance(elements[e], dict):
                    need = elements[e].get("min_coverage", elements[e].get("required_coverage"))
                row_op = f">= {float(need)}" if need is not None and mode != "partition" else op

                if covering_vars:
                    constraints.append(
                        Constraint(
                            name=f"cover_{elem_name}",
                            expression=f"{' + '.join(covering_vars)} {row_op}",
                        )
                    )
                else:
                    uncoverable.append(elem_name)

            # An element no set covers used to be silently skipped, and the
            # answer came back "optimal" with the element uncovered — the one
            # thing a covering model exists to prevent. Say so instead.
            if uncoverable:
                raise ValueError(
                    f"No set covers element(s): {', '.join(uncoverable)}. "
                    "Every element must appear in at least one set's coverage."
                )

        # A cap on how many sets may be chosen (p-median style). Public
        # facility cards state it as max_facilities.
        max_sets = user_input.get("max_sets", user_input.get("max_facilities"))
        if max_sets is not None and float(max_sets) > 0:
            constraints.append(
                Constraint(
                    name="max_sets",
                    expression=f"{' + '.join(v.name for v in variables)} <= {float(max_sets)}",
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
