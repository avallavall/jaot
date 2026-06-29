import type { ProjectRead } from "@/lib/types";

interface RenameDeps {
  modelId: string;
  next: string;
  current: string;
  setName: (name: string) => void;
  update: (id: string, body: { name: string }) => Promise<ProjectRead>;
  onError: () => void;
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
}: RenameDeps): Promise<void> {
  const trimmed = next.trim();
  if (!trimmed || trimmed === current || !modelId || modelId === "new") return;
  setName(trimmed); // optimistic
  try {
    await update(modelId, { name: trimmed });
  } catch {
    setName(current); // revert
    onError();
  }
}
