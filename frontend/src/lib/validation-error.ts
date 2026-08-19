/**
 * Reading a 422 the server refused a request with.
 *
 * FastAPI answers a bad body with Pydantic's own list:
 * `detail: [{type: "missing", loc: ["body", "objective"], msg: "Field required"}]`.
 * The client used to join the `msg` values and show them, so a model without an
 * objective was rejected with the two bare words "Field required" — which field
 * unsaid, and in English inside a page in another language.
 *
 * Here the list becomes two things: an English sentence that names the field
 * (for whoever reads the raw message, and for a client that is not a browser),
 * and a code plus the field names, which a screen renders in the reader's
 * language through `translateApiError`.
 */

/** One entry of FastAPI's 422 `detail` list. */
export interface FieldProblem {
  type?: string;
  msg?: string;
  loc?: unknown[];
}

/** Where the problem is, as a reader can act on it: `body`/`query` is plumbing. */
export function fieldPath(loc: unknown[] | undefined): string {
  if (!Array.isArray(loc)) return "";
  return loc
    .filter((part) => part !== "body" && part !== "query" && part !== "path")
    .map((part) => String(part))
    .join(".");
}

export interface ReadValidation {
  message: string;
  code?: string;
  params?: Record<string, unknown>;
}

/** Turn a 422 detail list into a message plus a translatable code. */
export function readValidationProblems(detail: FieldProblem[]): ReadValidation {
  const message = detail
    .map((problem) => {
      const where = fieldPath(problem.loc);
      const what = problem.msg ?? "";
      if (!where) return what || JSON.stringify(problem);
      return what ? `${where}: ${what}` : where;
    })
    .join("; ");

  const fields = [...new Set(detail.map((problem) => fieldPath(problem.loc)).filter(Boolean))];
  if (fields.length === 0) return { message };

  // "missing" and everything else read differently to whoever has to fix it:
  // one says add this, the other says this value is wrong.
  const allMissing = detail.every((problem) => problem.type === "missing");
  return {
    message,
    code: allMissing ? "validation.missing_fields" : "validation.invalid_fields",
    params: { fields: fields.join(", "), count: fields.length },
  };
}
