/**
 * Realistic optimization problem payloads for load tests.
 *
 * Three sizes let us exercise different credit tiers and solver durations.
 */

/** Small LP — 2 variables, 1 constraint. Solves instantly. */
export const PROBLEM_SMALL = {
  variables: [
    { name: "x", type: "continuous", lower_bound: 0 },
    { name: "y", type: "continuous", lower_bound: 0 },
  ],
  objective: { sense: "minimize", expression: "x + y" },
  constraints: [{ expression: "x + y >= 10", name: "c1" }],
};

/** Medium MIP — 10 variables (5 integer), 5 constraints. */
export const PROBLEM_MEDIUM = {
  variables: [
    { name: "x1", type: "integer", lower_bound: 0, upper_bound: 20 },
    { name: "x2", type: "integer", lower_bound: 0, upper_bound: 20 },
    { name: "x3", type: "integer", lower_bound: 0, upper_bound: 20 },
    { name: "x4", type: "integer", lower_bound: 0, upper_bound: 20 },
    { name: "x5", type: "integer", lower_bound: 0, upper_bound: 20 },
    { name: "y1", type: "continuous", lower_bound: 0 },
    { name: "y2", type: "continuous", lower_bound: 0 },
    { name: "y3", type: "continuous", lower_bound: 0 },
    { name: "y4", type: "continuous", lower_bound: 0 },
    { name: "y5", type: "continuous", lower_bound: 0 },
  ],
  objective: {
    sense: "maximize",
    expression: "3*x1 + 5*x2 + 2*x3 + 4*x4 + x5 + y1 + y2 + y3 + y4 + y5",
  },
  constraints: [
    { expression: "x1 + x2 + x3 <= 30", name: "supply_a" },
    { expression: "x4 + x5 + y1 <= 25", name: "supply_b" },
    { expression: "y2 + y3 + y4 + y5 <= 40", name: "supply_c" },
    { expression: "x1 + x4 + y2 >= 10", name: "demand_1" },
    { expression: "x2 + x5 + y3 >= 8", name: "demand_2" },
  ],
};

/**
 * Invalid payload — missing required 'variables' field.
 * Expected response: 422 Unprocessable Entity.
 */
export const PROBLEM_INVALID = {
  objective: { sense: "minimize", expression: "x + y" },
  constraints: [{ expression: "x + y >= 10", name: "c1" }],
  // variables intentionally omitted
};
