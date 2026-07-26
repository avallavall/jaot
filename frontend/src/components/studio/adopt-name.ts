import { humanizeProblemName } from "./assistant/formulation-adopt";

/** The name every project is created with (see studio/new). */
export const PLACEHOLDER_PROJECT_NAME = "Untitled Model";

/**
 * The name a project should take from a compiled model, or null to leave it alone.
 *
 * Only a project still carrying the placeholder is renamed: once someone has
 * titled their model by hand, a later compile must not overwrite that. The
 * assistant already adopted the name it invented for its formulation, so a model
 * built by chatting arrived in the list titled while one written in JModel — which
 * names itself through its objective — stayed "Untitled Model" forever.
 */
export function nameToAdopt(
  currentName: string,
  problemName: string | null | undefined,
): string | null {
  if (currentName.trim() !== PLACEHOLDER_PROJECT_NAME) return null;
  const candidate = (problemName ?? "").trim();
  if (!candidate) return null;
  const humanized = humanizeProblemName(candidate);
  return humanized === currentName.trim() ? null : humanized;
}
