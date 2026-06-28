import { api } from "@/lib/api";
import type { OptimizationProblem } from "@/lib/types";

const SOLVER_FORMAT_RE = /\.(mps|lp|cip)(\.gz)?$/i;
const MODEL_FILE_RE = /\.(json|mps|lp|cip)(\.gz)?$/i;

export interface ParsedModelFile {
  problem: OptimizationProblem;
  /** File name without its (optionally gzipped) extension — a sensible model name. */
  baseName: string;
}

/**
 * Parse a model file into an OptimizationProblem. Standard solver formats
 * (MPS/LP/CIP, optionally gzipped) are parsed server-side via the import
 * preview endpoint; JSON (the builder's own export format) is parsed locally.
 *
 * Shared by every "import a model from file" entry point (builder toolbar,
 * builder index) so they all accept the same formats. Throws on invalid
 * content — callers surface the error to the user.
 */
export async function parseModelFile(file: File): Promise<ParsedModelFile> {
  const baseName = file.name.replace(MODEL_FILE_RE, "");
  if (SOLVER_FORMAT_RE.test(file.name)) {
    const preview = await api.fileImport.preview(file);
    return { problem: preview.problem as OptimizationProblem, baseName };
  }
  const text = await file.text();
  const problem = JSON.parse(text) as OptimizationProblem;
  return { problem, baseName };
}
