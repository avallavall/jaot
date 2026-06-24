"""Cash flow generator — multi-period cash flow planning with credit line.

Models sequential periods with inflows, outflows, and optional borrowing.
Minimizes total interest cost while maintaining non-negative balance.
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


class CashFlowGenerator(BaseGenerator):
    """Generate multi-period cash flow planning problems.

    The balance carries forward each period:
      balance_t = balance_{t-1} + inflow_t - outflow_t + borrow_t
    Minimize total borrowing cost (interest).
    """

    def generate(self, user_input: dict[str, Any], params: dict[str, Any]) -> OptimizationProblem:
        periods = find_list_field(user_input, ["periods", "months", "quarters"])
        if not periods:
            raise ValueError(
                f"Cash flow requires a periods list. Got keys: {list(user_input.keys())}"
            )

        initial_balance = float(
            user_input.get("initial_balance", user_input.get("opening_balance", 0))
        )
        credit_rate = float(
            user_input.get("credit_line_rate", user_input.get("interest_rate", 0.01))
        )
        max_borrow = user_input.get("max_borrowing_per_period", user_input.get("credit_limit"))

        variables: list[Variable] = []
        cost_terms: list[str] = []

        for i, period in enumerate(periods):
            name = self.sanitize_name(period.get("name", f"period_{i + 1}"))
            var_name = f"borrow_{name}"

            variables.append(
                Variable(
                    name=var_name,
                    type=VariableType.CONTINUOUS,
                    lower_bound=0,
                    upper_bound=float(max_borrow) if max_borrow is not None else None,
                )
            )
            cost_terms.append(f"{credit_rate}*{var_name}")

        constraints: list[Constraint] = []

        # Cumulative balance must be non-negative at end of each period
        # balance_t = initial + SUM_{k=1..t}(inflow_k - outflow_k + borrow_k) >= 0
        cumulative_net = initial_balance
        for i, period in enumerate(periods):
            inflow = float(period.get("inflows", period.get("income", period.get("revenue", 0))))
            outflow = float(period.get("outflows", period.get("expenses", period.get("costs", 0))))
            cumulative_net += inflow - outflow

            borrow_vars = [v.name for v in variables[: i + 1]]
            borrow_expr = " + ".join(borrow_vars)

            name = self.sanitize_name(period.get("name", f"period_{i + 1}"))
            constraints.append(
                Constraint(
                    name=f"balance_{name}",
                    expression=f"{cumulative_net} + {borrow_expr} >= 0",
                )
            )

        return OptimizationProblem(
            name="cash_flow_planning",
            description=f"Minimize borrowing cost over {len(periods)} periods",
            variables=variables,
            objective=Objective(
                sense=ObjectiveSense.MINIMIZE,
                expression=" + ".join(cost_terms) if cost_terms else "0",
            ),
            constraints=constraints,
            options=SolverOptions(time_limit_seconds=30),
        )
