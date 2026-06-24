
// Error Extraction Utilities
// Provides helpers for extracting meaningful, user-facing error
// messages from API responses and unknown caught errors.

import { ApiError } from "./api";

/**
 * Extract a user-friendly error message from a caught error.
 *
 * Priority:
 * 1. ApiError.detail (backend-provided structured detail)
 * 2. ApiError.message (parsed from response body)
 * 3. Error.message (generic JS errors)
 * 4. Provided fallback string
 *
 * @param error   The caught error (unknown type from catch blocks)
 * @param fallback  A fallback message if no detail can be extracted
 * @returns A descriptive error string suitable for display in the UI
 */
export function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    // Prefer the structured detail from the backend when available
    return error.detail || error.message || fallback;
  }
  if (error instanceof Error) {
    return error.message || fallback;
  }
  if (typeof error === "string") {
    return error;
  }
  return fallback;
}

/**
 * Extract the HTTP status code from a caught error, if available.
 *
 * @param error  The caught error
 * @returns The HTTP status code, or undefined if not an ApiError
 */
export function getErrorStatus(error: unknown): number | undefined {
  if (error instanceof ApiError) {
    return error.status;
  }
  return undefined;
}
