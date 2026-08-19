/**
 * What a variable was allowed to be, and whether the answer pushed it there.
 *
 * The Solution Explorer has seven columns and four of them could never hold a
 * value: Lower Bound and Upper Bound were em-dashes written into the JSX, and
 * Binding and Slack always said "N/A" under a tooltip blaming MIP problems —
 * on a pure LP with two continuous variables. The bounds are in the execution
 * the page already loaded, under `input_data.variables`, so nothing was missing
 * but the wiring.
 */

/** The declared range of one variable. `null` means it was not bounded there. */
export interface VariableBounds {
  lower: number | null;
  upper: number | null;
}

/**
 * Anything this big is a solver's way of writing "no bound".
 *
 * SCIP writes 1e20, HiGHS writes 1e30 and an LP file can carry either. Printed
 * as a number it reads as a real limit the model does not have.
 */
const INFINITE = 1e19;

function finite(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.abs(value) >= INFINITE ? null : value;
}

/**
 * The declared bounds of every variable in a stored problem, by name.
 *
 * Reads the execution's own `input_data`, which is the problem exactly as it
 * was solved. Returns an empty map for anything that is not one, so a run
 * recorded before this — or one whose payload the list endpoint omits — simply
 * shows no bounds rather than failing.
 */
export function readVariableBounds(inputData: unknown): Record<string, VariableBounds> {
  const variables = (inputData as { variables?: unknown } | null | undefined)?.variables;
  if (!Array.isArray(variables)) return {};

  const bounds: Record<string, VariableBounds> = {};
  for (const entry of variables) {
    const row = entry as { name?: unknown; lower_bound?: unknown; upper_bound?: unknown };
    if (typeof row?.name !== "string") continue;
    bounds[row.name] = { lower: finite(row.lower_bound), upper: finite(row.upper_bound) };
  }
  return bounds;
}

/** Which bound a value is sitting on, and how far it is from the nearest one. */
export interface BoundStatus {
  /** The bound the value has reached, or null when it is between them. */
  at: "lower" | "upper" | null;
  /** Distance to the nearest declared bound, or null when there is none. */
  slack: number | null;
}

/**
 * How close a solved value came to the range it was allowed.
 *
 * The tolerance is the solvers' usual feasibility one, scaled by the size of
 * the bound: an integer at its upper bound of 3 comes back as 2.9999999996, and
 * a strict equality would call that "not at the bound".
 */
export function boundStatus(value: number, bounds: VariableBounds | undefined): BoundStatus {
  if (!bounds) return { at: null, slack: null };
  const { lower, upper } = bounds;

  const atLower = lower !== null && Math.abs(value - lower) <= tolerance(lower);
  const atUpper = upper !== null && Math.abs(value - upper) <= tolerance(upper);
  // A variable fixed to one number (lower === upper) is at both. Naming the
  // lower one is arbitrary but stable, and the slack of zero says the rest.
  const at = atLower ? "lower" : atUpper ? "upper" : null;

  const distances: number[] = [];
  if (lower !== null) distances.push(Math.abs(value - lower));
  if (upper !== null) distances.push(Math.abs(upper - value));
  const slack = distances.length > 0 ? Math.min(...distances) : null;

  return { at, slack: at !== null ? 0 : slack };
}

function tolerance(bound: number): number {
  return 1e-6 * Math.max(1, Math.abs(bound));
}
