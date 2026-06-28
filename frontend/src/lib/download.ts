/** Trigger a browser download of a Blob as a named file. */
export function downloadBlobAsFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  // Revoke after a tick so the click has a chance to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
