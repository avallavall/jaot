
// CSV Export Utilities
// RFC-4180 compliant CSV generation with UTF-8 BOM support.

/** Characters a spreadsheet reads as the start of a formula, not of text. */
const FORMULA_START = /^[=+\-@\t\r]/;

/** True for text a spreadsheet would read back as a plain number. */
function looksNumeric(str: string): boolean {
  return str.trim() !== "" && Number.isFinite(Number(str));
}

/**
 * Quote a single cell value per RFC 4180:
 * wrap in double-quotes and escape internal double-quotes by doubling.
 *
 * Excel and LibreOffice run a cell that opens with `=`, `+`, `-`, `@` or a
 * control character as a formula, quotes or no quotes. Model names, dataset
 * names, variable names and solver error text all come from whoever wrote
 * them, so a model named `=1+1` would compute in the reader's spreadsheet
 * instead of showing its name. A leading apostrophe makes the sheet read the
 * cell as text. A number keeps its sign: `-5` is a number, not a formula.
 */
export function quoteCell(value: string | number | null | undefined): string {
  const str = String(value ?? "");
  const safe = FORMULA_START.test(str) && !looksNumeric(str) ? `'${str}` : str;
  const escaped = safe.replace(/"/g, '""');
  return `"${escaped}"`;
}

/**
 * Build a CSV string from rows and trigger a browser download.
 * Includes UTF-8 BOM for Excel compatibility.
 */
export function downloadCSV(
  filename: string,
  rows: (string | number | null | undefined)[][],
): void {
  const csvContent = rows.map((row) => row.map(quoteCell).join(",")).join("\r\n");
  const blob = new Blob(["\uFEFF" + csvContent], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
