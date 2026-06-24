/**
 * Shared constants and utilities for file import (page + dialog).
 *
 * Single source of truth so both `/solve/import` page and the
 * `FileImportDialog` component stay in sync.
 */

/** File extensions the frontend accepts for upload. */
export const ACCEPTED_EXTENSIONS = [".lp", ".mps", ".cip", ".json"] as const;

/** Maximum upload size shown to the user (actual limit enforced by backend). */
export const MAX_FILE_SIZE_MB = 10;
export const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

/** Extract the lowercased extension from a filename (e.g. ".mps"). */
export function getFileExtension(name: string): string {
  const idx = name.lastIndexOf(".");
  return idx >= 0 ? name.slice(idx).toLowerCase() : "";
}

/** Check whether a File has an accepted extension. */
export function isAcceptedFile(file: File): boolean {
  return (ACCEPTED_EXTENSIONS as readonly string[]).includes(
    getFileExtension(file.name),
  );
}

/** Human-readable file size string. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
