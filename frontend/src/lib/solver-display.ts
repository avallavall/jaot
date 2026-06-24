/**
 * Solver brand-name display (Phase 07-simplify / R-7).
 *
 * Solver names travel through the API as lowercase enum strings
 * ("scip" / "highs" / "hexaly") but product UI must render the brand
 * capitalisation ("SCIP" / "HiGHS" / "Hexaly"). Unknown names fall back
 * to uppercase for forward compatibility when future solvers land.
 *
 * Solver names are NOT translated (Phase 5 + Phase 7 convention).
 */

export const SOLVER_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  scip: "SCIP",
  highs: "HiGHS",
  hexaly: "Hexaly",
};

export function solverDisplayName(name: string): string {
  return SOLVER_DISPLAY_NAMES[name.toLowerCase()] ?? name.toUpperCase();
}
