
// CSV Export Utilities
// RFC-4180 compliant CSV generation with UTF-8 BOM support.

/**
 * Quote a single cell value per RFC 4180:
 * wrap in double-quotes and escape internal double-quotes by doubling.
 */
export function quoteCell(value: string | number | null | undefined): string {
  const str = String(value ?? "");
  const escaped = str.replace(/"/g, '""');
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
