/**
 * Solver brand-name display (Phase 07-simplify / R-7).
 *
 * Solver names travel through the API as lowercase enum strings
 * ("scip" / "highs" / "cbc" / "glpk" / "jaos" / "hexaly") but product UI must
 * render the brand capitalisation ("SCIP" / "HiGHS" / "CBC" / "GLPK" / "JAOS" /
 * "Hexaly"). Unknown
 * names fall back to uppercase for forward compatibility when future solvers
 * land.
 *
 * Solver names are NOT translated (Phase 5 + Phase 7 convention).
 */

export const SOLVER_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  scip: "SCIP",
  highs: "HiGHS",
  hexaly: "Hexaly",
  // The uppercase fallback below already produces these three. They are listed
  // anyway so this map reads as the roster of solvers JAOT ships.
  cbc: "CBC",
  glpk: "GLPK",
  jaos: "JAOS",
};

export function solverDisplayName(name: string): string {
  return SOLVER_DISPLAY_NAMES[name.toLowerCase()] ?? name.toUpperCase();
}

/**
 * The colour a chart draws a solver in: the same in every chart, readable in
 * both themes (`--solver-*` in globals.css). Charts used to take the chart
 * palette by position, which left the fifth solver, JAOS, nearly invisible on
 * the dark theme. An unknown solver still gets a palette colour by position.
 */
export function solverColor(name: string, fallbackIndex = 0): string {
  const key = name.toLowerCase();
  if (key in SOLVER_DISPLAY_NAMES) return `var(--solver-${key})`;
  return `var(--chart-${(Math.max(0, fallbackIndex) % 5) + 1})`;
}

/** The subset of next-intl's translator this module needs. */
interface Translator {
  (key: string): string;
  has: (key: string) => boolean;
}

/**
 * The one-line description shown next to a solver in the picker.
 *
 * The API sends one, in English. When the messages carry a translation for that
 * solver it wins, so the picker reads in the user's language. A solver with no
 * translation still gets its English line rather than nothing — that is what
 * keeps a solver added on the backend visible before the messages catch up.
 */
export function solverDescription(
  name: string,
  apiDescription: string | undefined,
  t: Translator,
): string | undefined {
  const key = `${name}.description`;
  return t.has(key) ? t(key) : apiDescription;
}
