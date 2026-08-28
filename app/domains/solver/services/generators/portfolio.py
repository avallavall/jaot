"""Portfolio generator — portfolio optimization problems."""

from typing import Any

from app.domains.solver.services.generators.base import BaseGenerator
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    Variable,
    VariableType,
)


class PortfolioGenerator(BaseGenerator):
    """Generate portfolio optimization problems.

    Linear approximation of Markowitz: maximize expected return subject to
    a weighted-risk budget constraint. Supports cardinality and sector constraints.
    """

    @staticmethod
    def _find_assets(user_input: dict[str, Any]) -> list[dict[str, Any]]:
        """Auto-detect the asset/item list from domain-specific input."""
        if "assets" in user_input and isinstance(user_input["assets"], list):
            return user_input["assets"]
        for _key, val in user_input.items():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val
        return []

    @staticmethod
    def _find_budget(user_input: dict[str, Any]) -> float:
        """Auto-detect the budget/capacity scalar."""
        for field in ("total_budget", "budget", "risk_budget", "capacity"):
            if field in user_input and not isinstance(user_input[field], (list, dict)):
                return float(user_input[field])
        return 100000.0

    def _generate_selection(
        self,
        user_input: dict[str, Any],
        assets: list[dict[str, Any]],
        total_budget: float,
        params: dict[str, Any],
    ) -> OptimizationProblem:
        """Pick whole assets, each consuming a stated amount of capital.

        The card says which field carries that amount (``weight_field``), how
        the return is stated (``return_field``, and ``return_mode`` when it is a
        rate on the weight rather than an absolute figure), and what eats into
        it (``return_discount_field``: an expected loss ratio nets a premium
        down). Saying it beats guessing, and it is what makes every number in
        the input reach the model.
        """
        weight_field = params["weight_field"]
        return_field = params.get("return_field", "expected_return")
        return_mode = params.get("return_mode", "absolute")
        discount_field = params.get("return_discount_field")
        risk_field = params.get("risk_field", "risk")
        risk_limit_field = params.get("risk_limit_field")

        variables: list[Variable] = []
        constraints: list[Constraint] = []
        return_terms: list[str] = []
        weight_terms: list[str] = []
        risk_terms: list[str] = []

        for i, asset in enumerate(assets):
            a_name = self.sanitize_name(asset.get("name", f"asset_{i}"))
            weight = asset.get(weight_field)
            if weight is None:
                raise ValueError(
                    f"Asset '{asset.get('name', i)}' states no '{weight_field}', so the "
                    "budget cannot know what it consumes."
                )
            weight = float(weight)

            raw_return = asset.get(return_field)
            if raw_return is None:
                raise ValueError(f"Asset '{asset.get('name', i)}' states no '{return_field}'.")
            value = (
                float(raw_return) * weight if return_mode == "rate_on_weight" else float(raw_return)
            )
            if discount_field is not None:
                discount = asset.get(discount_field)
                if discount is None:
                    raise ValueError(
                        f"Asset '{asset.get('name', i)}' states no '{discount_field}'."
                    )
                value *= 1 - float(discount)

            variables.append(Variable(name=a_name, type=VariableType.BINARY))
            return_terms.append(f"{round(value, 6)}*{a_name}")
            weight_terms.append(f"{weight}*{a_name}")

            risk = asset.get(risk_field)
            if risk is not None:
                risk_terms.append(f"{round(float(risk) * weight, 6)}*{a_name}")

        constraints.append(
            Constraint(
                name="budget",
                expression=f"{' + '.join(weight_terms)} <= {total_budget}",
            )
        )

        # A weighted risk ceiling, stated as a rate on the money committed.
        if risk_limit_field and risk_terms:
            limit = user_input.get(risk_limit_field)
            if limit is None:
                raise ValueError(f"Input states no '{risk_limit_field}' to cap risk with.")
            # sum(risk_i * w_i * x_i) <= limit * sum(w_i * x_i)
            scaled = " + ".join(
                f"{round(float(w.split('*')[0]) * float(limit), 6)}*{w.split('*')[1]}"
                for w in weight_terms
            )
            constraints.append(
                Constraint(
                    name="risk_limit",
                    expression=f"{' + '.join(risk_terms)} - ({scaled}) <= 0",
                )
            )

        max_assets = user_input.get("max_assets", 0)
        if max_assets and float(max_assets) > 0:
            constraints.append(
                Constraint(
                    name="max_assets",
                    expression=f"{' + '.join(v.name for v in variables)} <= {float(max_assets)}",
                )
            )

        return OptimizationProblem(
            name="portfolio_selection",
            description=(
                f"Select from {len(assets)} assets within a budget of {total_budget:,.0f}"
            ),
            variables=variables,
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression=" + ".join(return_terms)),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        assets = self._find_assets(user_input)
        total_budget = self._find_budget(user_input)

        # Whole-asset selection. A property or an insurance policy is taken or
        # not, and it consumes a stated amount of capital or exposure. Treating
        # it as a fraction in [0, 1] and then writing "sum of fractions <=
        # 8000000" made the budget unreachable, so the answer was always "buy
        # every one of them" and the prices were never read at all.
        weight_field = params.get("weight_field")
        if weight_field:
            return self._generate_selection(user_input, assets, total_budget, params)
        max_risk = user_input.get("max_risk", 0)
        min_return = user_input.get("min_return", 0)
        max_assets = user_input.get("max_assets", 0)
        sector_limits = user_input.get("sector_limits", {})

        variables: list[Variable] = []
        return_terms: list[str] = []
        risk_terms: list[str] = []
        alloc_terms: list[str] = []
        constraints: list[Constraint] = []

        for asset in assets:
            a_name = self.sanitize_name(asset.get("name", f"asset_{len(variables)}"))
            min_alloc = asset.get("min_allocation", asset.get("min_spend", 0))
            max_alloc = asset.get("max_allocation", asset.get("max_spend", 1))
            exp_return = asset.get("expected_return", asset.get("premium", asset.get("return", 0)))
            risk = asset.get("risk", asset.get("expected_loss_ratio", 0))

            variables.append(
                Variable(
                    name=a_name,
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=max_alloc,
                )
            )

            return_terms.append(f"{exp_return}*{a_name}")
            risk_terms.append(f"{risk}*{a_name}")
            alloc_terms.append(a_name)

            if min_alloc > 0 and max_assets > 0:
                pass  # handled below with binary vars
            elif min_alloc > 0:
                constraints.append(
                    Constraint(
                        name=f"min_alloc_{a_name}",
                        expression=f"{a_name} >= {min_alloc}",
                    )
                )

        # Budget constraint: explicit mode param, or infer from allocation scale
        alloc_mode = params.get(
            "allocation_mode",
            user_input.get("allocation_mode", "auto"),
        )
        if alloc_mode == "fraction" or (alloc_mode == "auto" and total_budget <= 1):
            constraints.append(
                Constraint(name="budget", expression=f"{' + '.join(alloc_terms)} == 1")
            )
        else:
            constraints.append(
                Constraint(
                    name="budget",
                    expression=f"{' + '.join(alloc_terms)} <= {total_budget}",
                )
            )

        if max_risk > 0:
            constraints.append(
                Constraint(
                    name="max_risk",
                    expression=f"{' + '.join(risk_terms)} <= {max_risk}",
                )
            )

        if min_return > 0:
            constraints.append(
                Constraint(
                    name="min_return",
                    expression=f"{' + '.join(return_terms)} >= {min_return}",
                )
            )

        # Cardinality constraint
        if max_assets > 0:
            binary_vars: list[str] = []
            for asset in assets:
                a_name = self.sanitize_name(asset.get("name", ""))
                max_alloc = asset.get("max_allocation", 1)
                min_alloc = asset.get("min_allocation", 0)
                y_name = f"y_{a_name}"

                variables.append(Variable(name=y_name, type=VariableType.BINARY))
                binary_vars.append(y_name)

                constraints.append(
                    Constraint(
                        name=f"link_upper_{a_name}",
                        expression=f"{a_name} - {max_alloc}*{y_name} <= 0",
                    )
                )
                if min_alloc > 0:
                    constraints.append(
                        Constraint(
                            name=f"link_lower_{a_name}",
                            expression=f"{a_name} - {min_alloc}*{y_name} >= 0",
                        )
                    )

            constraints.append(
                Constraint(
                    name="max_assets",
                    expression=f"{' + '.join(binary_vars)} <= {max_assets}",
                )
            )

        # Sector constraints
        if sector_limits:
            sectors: dict[str, list[str]] = {}
            for asset in assets:
                sector = asset.get("sector")
                if sector:
                    a_name = self.sanitize_name(asset.get("name", ""))
                    sectors.setdefault(sector, []).append(a_name)

            for sector, max_frac in sector_limits.items():
                if sector in sectors:
                    sector_vars = sectors[sector]
                    constraints.append(
                        Constraint(
                            name=f"sector_{self.sanitize_name(sector)}",
                            expression=f"{' + '.join(sector_vars)} <= {max_frac}",
                        )
                    )

        return OptimizationProblem(
            name="portfolio_optimization",
            description=f"Optimize portfolio of {len(assets)} assets with budget {total_budget:,.0f}",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE,
                expression=" + ".join(return_terms) if return_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=60),
        )
