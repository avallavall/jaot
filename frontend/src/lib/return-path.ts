/**
 * The "come back here after signing in" path.
 *
 * A protected page bounces an anonymous visitor to /login and hands over where
 * they were going. That value ends up in a URL the visitor controls, so it is
 * an open-redirect vector: only a path on this site may ever be honoured.
 *
 * Paths here are LOCALE-FREE — they travel through next-intl's router, which
 * re-applies the active locale prefix on navigation.
 */

/** Query parameter carrying the post-login destination. */
export const RETURN_PARAM = "next";

/** Query parameter that tells the login page a session ran out under the user. */
export const EXPIRED_PARAM = "expired";

/** Where a signed-in user lands when there is nothing to return to. */
export function defaultLandingPath(isAdmin: boolean | undefined): string {
  return isAdmin ? "/admin" : "/studio";
}

/**
 * Accept `candidate` only if it is an in-app path, otherwise fall back.
 *
 * Rejected: absolute URLs, protocol-relative ("//evil.com", "/\evil.com"),
 * anything not starting with "/", and the auth pages themselves — returning to
 * /login after logging in is a loop, not a destination.
 */
export function safeReturnPath(
  candidate: string | null | undefined,
  fallback: string,
): string {
  if (!candidate || !candidate.startsWith("/")) return fallback;
  if (candidate.startsWith("//") || candidate.startsWith("/\\")) return fallback;

  const path = candidate.split(/[?#]/)[0];
  const AUTH_PAGES = ["/login", "/signup", "/forgot-password", "/reset-password", "/verify-email"];
  if (AUTH_PAGES.some((page) => path === page || path.startsWith(`${page}/`))) return fallback;

  return candidate;
}

/**
 * Build the login URL that remembers where the visitor was heading.
 *
 * `expired` adds the flag the login page reads to say why they are there. It is
 * set only when a session ran out under somebody who had one; an anonymous
 * visitor who simply opened a protected page is not told their session expired.
 */
export function loginPathReturningTo(
  pathname: string,
  search = "",
  expired = false,
): string {
  const target = `${pathname}${search}`;
  const query = new URLSearchParams();
  if (safeReturnPath(target, "") !== "") query.set(RETURN_PARAM, target);
  if (expired) query.set(EXPIRED_PARAM, "1");
  const qs = query.toString();
  return qs ? `/login?${qs}` : "/login";
}
