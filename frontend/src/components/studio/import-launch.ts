import { api } from "@/lib/api";
import { parseModelFile } from "@/lib/builder/import-model";

/**
 * Parse a model file (MPS/LP/CIP/JSON, optionally gzipped) and create a ModelProject
 * seeded with ONLY its `model_json` — the workspace derives the canvas from the model
 * on load (`resolveDraftCanvas`), so large imports stay light (no giant canvas blob).
 * Returns the new project id (caller navigates to it). Throws on parse / API failure.
 */
export async function importFileToProject(file: File, workspaceId?: string): Promise<string> {
  const { problem, baseName } = await parseModelFile(file);
  const project = await api.createProject(
    { name: baseName || "Imported model", workspace_id: workspaceId },
    workspaceId
  );
  await api.updateProjectDraft(
    project.id,
    { model_json: problem },
    project.draft_lock_version,
    workspaceId
  );
  return project.id;
}
