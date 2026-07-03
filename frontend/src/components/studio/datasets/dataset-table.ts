/**
 * Pure transforms behind the dataset TABLE view (S2b): a structured editor over
 * the same JSON text the raw editor owns. The text stays the single source of
 * truth — the table parses it into a `TableModel` and serializes every edit
 * back, so switching views can never fork the data.
 */

export interface TableSet {
  name: string;
  /** Members as the user types them — comma-separated; parsed on serialize. */
  membersText: string;
}

export interface TableScalarParam {
  name: string;
  kind: "scalar";
  /** Kept as text while typing; empty = not provided (serialize omits it). */
  value: string;
}

export interface TableIndexedRow {
  parts: string[];
  value: string;
}

export interface TableIndexedParam {
  name: string;
  kind: "indexed";
  arity: number;
  rows: TableIndexedRow[];
}

export type TableParam = TableScalarParam | TableIndexedParam;

export interface TableModel {
  sets: TableSet[];
  params: TableParam[];
}

/**
 * Parse dataset JSON into a table model, or `null` when the text is not valid
 * JSON / not our shape (the dialog then stays on the raw JSON view).
 */
export function tableFromJson(text: string): TableModel | null {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const rawSets = (data as Record<string, unknown>).sets ?? {};
  const rawParams = (data as Record<string, unknown>).params ?? {};
  if (!isRecord(rawSets) || !isRecord(rawParams)) return null;

  const sets: TableSet[] = [];
  for (const [name, members] of Object.entries(rawSets)) {
    if (!Array.isArray(members)) return null;
    if (!members.every((m) => typeof m === "string" || typeof m === "number")) return null;
    sets.push({ name, membersText: members.map(String).join(", ") });
  }

  const params: TableParam[] = [];
  for (const [name, value] of Object.entries(rawParams)) {
    if (typeof value === "number") {
      params.push({ name, kind: "scalar", value: String(value) });
      continue;
    }
    if (isRecord(value)) {
      const rows: TableIndexedRow[] = [];
      let arity = 1;
      for (const [key, raw] of Object.entries(value)) {
        if (typeof raw !== "number") return null;
        const parts = key.split(",");
        arity = Math.max(arity, parts.length);
        rows.push({ parts, value: String(raw) });
      }
      // Ragged keys are a data error the JSON view + S5 check surface better.
      if (rows.some((r) => r.parts.length !== arity)) return null;
      params.push({ name, kind: "indexed", arity, rows });
      continue;
    }
    return null;
  }
  return { sets, params };
}

/**
 * Serialize the table model back to pretty JSON. Incomplete entries (an empty
 * index cell or a non-numeric value) are OMITTED rather than serialized broken
 * — the S5 live check and the server validation then say what is missing.
 */
export function tableToJson(model: TableModel): string {
  const sets: Record<string, string[]> = {};
  for (const s of model.sets) {
    sets[s.name] = s.membersText
      .split(",")
      .map((m) => m.trim())
      .filter(Boolean);
  }
  const params: Record<string, number | Record<string, number>> = {};
  for (const p of model.params) {
    if (p.kind === "scalar") {
      const num = Number(p.value);
      if (p.value.trim() !== "" && Number.isFinite(num)) params[p.name] = num;
      continue;
    }
    const values: Record<string, number> = {};
    for (const row of p.rows) {
      const num = Number(row.value);
      if (row.parts.some((part) => !part.trim()) || row.value.trim() === "") continue;
      if (!Number.isFinite(num)) continue;
      values[row.parts.map((part) => part.trim()).join(",")] = num;
    }
    params[p.name] = values;
  }
  return JSON.stringify({ sets, params }, null, 2);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
