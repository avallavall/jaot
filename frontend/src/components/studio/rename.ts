import type { ProjectRead } from "@/lib/types";

interface RenameDeps {
  modelId: string;
  next: string;
  current: string;
  setName: (name: string) => void;
  update: (id: string, body: { name: string }) => Promise<ProjectRead>;
  onError: () => void;
  /** Fresh store name, used so a failed PATCH only reverts its OWN optimistic
   * write — not a rename another path (e.g. the assistant) landed meanwhile. */
  getName?: () => string;
}

/** What a blur on the name input should do, once Escape and blanks are accounted for. */
export type RenameBlurOutcome =
  | { action: "discard"; draft: string }
  | { action: "commit"; draft: string };

/**
 * Decide what a blur on the model-name input means. Split out of the shell because
 * `blur()` runs synchronously inside the keydown handler, so the blur handler still
 * closes over the pre-Escape draft — the cancel intent has to travel as an argument,
 * not as React state.
 *
 * Escape discards the edit outright (no PATCH). A blank name is not a rename either:
 * it restores the stored name instead of leaving the field visually empty.
 */
export function resolveRenameBlur({
  draft,
  storedName,
  cancelled,
}: {
  draft: string;
  storedName: string;
  cancelled: boolean;
}): RenameBlurOutcome {
  if (cancelled || !draft.trim()) return { action: "discard", draft: storedName };
  return { action: "commit", draft: draft.trim() };
}

/**
 * Commit a model rename: optimistically update the store, persist via PATCH, and
 * revert the store on failure. No-op when the name is blank, unchanged, or the
 * project isn't persisted yet ("new"). Pure (deps injected) so it's unit-testable
 * without rendering the workspace shell.
 */
export async function commitRename({
  modelId,
  next,
  current,
  setName,
  update,
  onError,
  getName,
}: RenameDeps): Promise<void> {
  const trimmed = next.trim();
  if (!trimmed || trimmed === current || !modelId || modelId === "new") return;
  setName(trimmed); // optimistic
  try {
    await update(modelId, { name: trimmed });
  } catch {
    // revert only our own optimistic write
    if (!getName || getName() === trimmed) setName(current);
    onError();
  }
}
