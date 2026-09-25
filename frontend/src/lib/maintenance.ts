/**
 * What the frontend knows about maintenance mode.
 *
 * Three places read it: the proxy decides who sees the maintenance page, the
 * page decides whether it should be showing at all, and the overlay decides
 * whether to repeat the notice. This is a plain module (no "use client") so a
 * server component can import the constants as values.
 */

/** Set by the proxy on a request it rewrote to the maintenance page. */
export const MAINTENANCE_REWRITE_HEADER = "x-jaot-maintenance";

/** Marks the maintenance page in the DOM, so the overlay does not repeat it. */
export const MAINTENANCE_PAGE_ATTRIBUTE = "data-maintenance-page";

const BACKEND_URL =
  process.env.API_PROXY_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

/**
 * Ask the API's health endpoint whether the site is in maintenance.
 *
 * Any failure reads as "not in maintenance". A health check that cannot be
 * reached must not lock every visitor out of a site that may be working.
 */
export async function fetchMaintenanceMode(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/v2/health`, {
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return false;
    const data = await res.json();
    return data?.maintenance === true;
  } catch {
    return false;
  }
}
