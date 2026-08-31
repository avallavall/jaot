"""Production generator — production planning and budget allocation problems."""

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


class ProductionGenerator(BaseGenerator):
    """Generate production planning problems.

    Also handles budget allocation as a configuration variant
    (continuous variables, budget as resource constraint).
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        products = user_input.get("products", [])
        resources = user_input.get(
            "resources",
            user_input.get("raw_materials", user_input.get("reactors", [])),
        )

        # Handle period-based production/resource allocation (e.g., reservoir operation)
        if not products and "periods" in user_input:
            return self._generate_periodic(user_input, params)

        variables: list[Variable] = []
        profit_terms: list[str] = []

        # A resource's "usage" map is keyed by whatever the user typed, and the
        # variables are sanitized. The feed-cost loop read the raw key and the
        # capacity loop read the sanitized one, so a product written "Dining
        # Chairs" kept its objective term and vanished from every resource row:
        # no ceiling on it at all, and an unbounded model reported as optimal.
        # Key every usage map the same way the variables are keyed, once.
        self.reject_name_collisions(
            [self.sanitize_name(p.get("name", "")) for p in products],
            [p.get("name") for p in products],
            "Products",
        )
        product_names = {self.sanitize_name(p.get("name", "")) for p in products}
        usage_by_resource: list[dict[str, Any]] = []
        for r in resources:
            usage_map = {self.sanitize_name(k): v for k, v in (r.get("usage") or {}).items()}
            unknown = sorted(set(usage_map) - product_names)
            if unknown:
                raise ValueError(
                    f"Resource '{r.get('name', 'resource')}' states usage for "
                    f"{unknown}, which match no product. Products are "
                    f"{sorted(product_names)}."
                )
            usage_by_resource.append(usage_map)

        for p in products:
            name = self.sanitize_name(p.get("name", f"product_{len(variables)}"))
            min_prod = p.get("min_production", 0)
            max_prod = p.get("max_production")
            profit = p.get("profit_per_unit", p.get("price_per_unit", 1))

            variables.append(
                Variable(
                    name=name,
                    type=VariableType.INTEGER
                    if p.get("integer", True)
                    else VariableType.CONTINUOUS,
                    lower_bound=min_prod,
                    upper_bound=max_prod,
                )
            )

            # What the card calls profit is the price less what the unit eats.
            # Reading only the price made every feedstock's cost decoration and
            # a card that says "at minimum cost" maximize revenue instead.
            feed_cost = 0.0
            for r, usage_map in zip(resources, usage_by_resource, strict=True):
                per_unit = r.get("cost_per_unit", r.get("cost"))
                usage = usage_map.get(name)
                if per_unit is not None and usage:
                    feed_cost += float(per_unit) * float(usage)
            profit_terms.append(f"{round(float(profit) - feed_cost, 6)}*{name}")

        constraints: list[Constraint] = []

        for r, usage in zip(resources, usage_by_resource, strict=True):
            r_name = r.get("name", "resource")
            available = r.get("available", 100)

            usage_terms = []
            for p in products:
                p_name = self.sanitize_name(p.get("name", ""))
                if p_name in usage:
                    usage_terms.append(f"{usage[p_name]}*{p_name}")

            if usage_terms:
                constraints.append(
                    Constraint(
                        name=self.sanitize_name(r_name),
                        expression=f"{' + '.join(usage_terms)} <= {available}",
                    )
                )

        # Where the work physically happens. "resources" falls back to
        # raw_materials first, so a card listing BOTH raw materials and reactors
        # had its reactors read by nothing: no throughput limit, no operating
        # cost, and the plan was free to make its maximum of every product on a
        # plant that could not hold it.
        reactors = user_input.get("reactors") or user_input.get("machines") or []
        if reactors and products:
            for r in reactors:
                r_name = self.sanitize_name(r.get("name", "reactor"))
                throughput = r.get("max_throughput", r.get("capacity"))
                conversion = float(r.get("conversion_rate", 1) or 1)
                op_cost = float(r.get("operating_cost", 0) or 0)
                if throughput is None:
                    raise ValueError(f"Reactor '{r.get('name', r_name)}' states no throughput.")

                load_terms = []
                for p in products:
                    p_name = self.sanitize_name(p.get("name", ""))
                    run = f"run_{p_name}_{r_name}"
                    variables.append(
                        Variable(name=run, type=VariableType.CONTINUOUS, lower_bound=0)
                    )
                    load_terms.append(run)
                    # A less efficient reactor burns more feed for the same
                    # output, so its hour costs more per unit produced.
                    profit_terms.append(f"-{round(op_cost / conversion, 6)}*{run}")

                constraints.append(
                    Constraint(
                        name=f"throughput_{r_name}",
                        expression=f"{' + '.join(load_terms)} <= {float(throughput)}",
                    )
                )

            # Everything produced has to have run somewhere.
            for p in products:
                p_name = self.sanitize_name(p.get("name", ""))
                runs = [
                    f"run_{p_name}_{self.sanitize_name(r.get('name', 'reactor'))}" for r in reactors
                ]
                constraints.append(
                    Constraint(
                        name=f"made_on_{p_name}",
                        expression=f"{' + '.join(runs)} - {p_name} == 0",
                    )
                )

        return OptimizationProblem(
            name="production_planning",
            description=f"Plan production for {len(products)} products",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(profit_terms) if profit_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )

    def _generate_periodic(
        self, user_input: dict[str, Any], params: dict[str, Any]
    ) -> OptimizationProblem:
        """Multi-period production/resource allocation (e.g., reservoir operation)."""
        num_periods = int(user_input.get("periods", 6))
        capacity = float(user_input.get("reservoir_capacity", user_input.get("capacity", 100000)))
        initial = float(user_input.get("initial_volume", user_input.get("initial", 0)))

        inflows = user_input.get("inflows", [])
        demands = user_input.get("irrigation_demand", user_input.get("demand", []))

        variables: list[Variable] = []
        constraints: list[Constraint] = []

        # Release variables per period
        for t in range(1, num_periods + 1):
            variables.append(
                Variable(
                    name=f"release_{t}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=capacity,
                )
            )
            # Volume (state) variable
            variables.append(
                Variable(
                    name=f"vol_{t}",
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=capacity,
                )
            )

        # Balance constraints: vol_t = vol_{t-1} + inflow_t - release_t
        for t in range(1, num_periods + 1):
            inflow = 0.0
            for inf in inflows:
                if inf.get("period") == t:
                    inflow = float(inf.get("volume", 0))
                    break

            prev_vol = f"vol_{t - 1}" if t > 1 else str(initial)
            if t == 1:
                # vol_1 = initial + inflow_1 - release_1
                constraints.append(
                    Constraint(
                        name=f"balance_{t}",
                        expression=f"vol_{t} + release_{t} == {initial + inflow}",
                    )
                )
            else:
                constraints.append(
                    Constraint(
                        name=f"balance_{t}",
                        expression=f"vol_{t} - {prev_vol} + release_{t} == {inflow}",
                    )
                )

        # Meet irrigation demand
        for t in range(1, num_periods + 1):
            demand = 0.0
            for d in demands:
                if isinstance(d, dict) and d.get("period") == t:
                    demand = float(d.get("volume", 0))
                    break
            if demand > 0:
                constraints.append(
                    Constraint(
                        name=f"demand_{t}",
                        expression=f"release_{t} >= {demand}",
                    )
                )

        # Maximize total release (useful water)
        obj_terms = [f"release_{t}" for t in range(1, num_periods + 1)]

        return OptimizationProblem(
            name="periodic_production",
            description=f"Multi-period resource allocation over {num_periods} periods",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(obj_terms),
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )


class BudgetAllocationGenerator(BaseGenerator):
    """Generate budget allocation problems.

    Kept as a separate generator for backward compatibility with existing
    templates that use generator_type="budget_allocation".
    """

    #: The same problem is written with department words or programme words.
    _MIN_KEYS = ("min_allocation", "min_funding", "min_budget")
    _MAX_KEYS = ("max_allocation", "max_funding", "max_budget")
    _RETURN_KEYS = ("expected_roi", "benefit_per_dollar", "roi", "return_per_unit", "benefit")

    @staticmethod
    def _pick(row: dict[str, Any], keys: tuple[str, ...], default: float) -> float:
        for key in keys:
            if row.get(key) is not None:
                return float(row[key])
        return default

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        total_budget = user_input.get("total_budget", user_input.get("budget", 100000))
        departments = find_list_field(
            user_input, ["departments", "programs", "areas", "categories"], fallback=False
        )
        objective_type = user_input.get("objective", "maximize_roi")

        if not departments:
            raise ValueError(
                "Budget allocation requires a list of departments/programs to fund. "
                f"Got keys: {list(user_input.keys())}"
            )

        variables: list[Variable] = []
        objective_terms: list[str] = []

        for dept in departments:
            name = self.sanitize_name(dept.get("name", f"dept_{len(variables)}"))
            min_alloc = self._pick(dept, self._MIN_KEYS, 0)
            max_alloc = self._pick(dept, self._MAX_KEYS, float(total_budget))
            roi = self._pick(dept, self._RETURN_KEYS, 1.0)

            variables.append(
                Variable(
                    name=name,
                    type=VariableType.CONTINUOUS,
                    lower_bound=min_alloc,
                    upper_bound=max_alloc,
                )
            )

            objective_terms.append(f"{roi}*{name}")

        all_vars = " + ".join(v.name for v in variables)
        constraints = [
            Constraint(
                name="total_budget",
                expression=f"{all_vars} <= {total_budget}",
            )
        ]

        sense = ObjectiveSense.MAXIMIZE if "max" in objective_type else ObjectiveSense.MINIMIZE
        objective_expr = " + ".join(objective_terms) if objective_terms else "0"

        return OptimizationProblem(
            name="budget_allocation",
            description=f"Allocate ${total_budget:,.0f} across {len(departments)} departments",
            variables=variables,
            objective=Objective(sense=sense, expression=objective_expr),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
