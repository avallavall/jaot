import type { ErrorTranslator } from "@/lib/errors";

/**
 * A compile failure the JModel editor shows.
 *
 * The box around it was already translated ("Error de compilación:", "El
 * modelo activo sigue siendo el último válido") while the sentence inside it —
 * the one part a reader needs, naming what is wrong and where — stayed
 * English. The compiler now names its common failures with a code, and this
 * renders the code's translation when there is one.
 *
 * Roughly fifteen of the compiler's hundred messages carry a code today. The
 * rest fall back to the English text, which is where all of them started;
 * adding one is a code at the raise site plus five strings.
 */
export interface JModelCompileError {
  message: string;
  position?: number | null;
  code?: string | null;
  params?: Record<string, string | number> | null;
}

export function jmodelErrorText(
  error: JModelCompileError | null | undefined,
  t: ErrorTranslator,
): string {
  if (!error) return "";
  if (error.code && t.has(error.code)) {
    return t(error.code, (error.params ?? {}) as Record<string, string | number>);
  }
  return error.message;
}
