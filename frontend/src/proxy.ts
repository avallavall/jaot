import { type NextRequest, NextResponse } from "next/server";
import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";
import { MAINTENANCE_REWRITE_HEADER, fetchMaintenanceMode } from "./lib/maintenance";

const intlMiddleware = createMiddleware(routing);

let maintenanceCache: { value: boolean; expiresAt: number } | null = null;
const CACHE_TTL_MS = 15_000; // 15 seconds

async function isMaintenanceMode(): Promise<boolean> {
  const now = Date.now();
  if (maintenanceCache && now < maintenanceCache.expiresAt) {
    return maintenanceCache.value;
  }
  // An unreachable health check reads as "not in maintenance": don't block users.
  const value = await fetchMaintenanceMode();
  maintenanceCache = { value, expiresAt: now + CACHE_TTL_MS };
  return value;
}

// Paths that should never redirect to maintenance
const MAINTENANCE_BYPASS_PREFIXES = [
  "/maintenance",
  "/admin",
  "/api",
  "/_next",
  "/_vercel",
  "/login",
  "/health",
];

function shouldBypassMaintenance(pathname: string): boolean {
  // Strip locale prefix (e.g., /es/admin → /admin)
  const stripped = pathname.replace(/^\/[a-z]{2}(\/|$)/, "/");
  return MAINTENANCE_BYPASS_PREFIXES.some((p) => stripped.startsWith(p));
}

function isAdminRequest(request: NextRequest): boolean {
  // Check for admin cookie — the cookie contains a JWT, but we only need
  // to know it exists. The backend will validate it properly.
  return request.cookies.has("jaot_access_token");
}

export default async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip maintenance check for bypassed paths, static files, and admin users
  if (
    !shouldBypassMaintenance(pathname) &&
    !isAdminRequest(request) &&
    !pathname.includes(".")
  ) {
    const maintenance = await isMaintenanceMode();
    if (maintenance) {
      // Determine locale from URL or default
      const localeMatch = pathname.match(/^\/([a-z]{2})(\/|$)/);
      const locale = localeMatch?.[1] ?? routing.defaultLocale;
      const url = request.nextUrl.clone();
      url.pathname = `/${locale}/maintenance`;
      // Tell the page it was put there by this check. Without the mark it
      // asks the API itself, for a visitor who typed /maintenance by hand.
      const requestHeaders = new Headers(request.headers);
      requestHeaders.set(MAINTENANCE_REWRITE_HEADER, "1");
      return NextResponse.rewrite(url, { request: { headers: requestHeaders } });
    }
  }

  return intlMiddleware(request);
}

export const config = {
  matcher: [
    // Match all pathnames except API routes, MCP, .well-known, static files, and Next.js internals
    "/((?!api|mcp|_next|_vercel|\\.well-known|.*\\..*).*)",
  ],
};
