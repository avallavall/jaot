/**
 * Resilient server-side fetch for SSR pages whose visible content is rendered
 * client-side and whose SSR fetch only feeds SEO metadata + JSON-LD.
 *
 * Three outcomes, deliberately distinct:
 *   - `ok`        — got the resource; use it for rich metadata / JSON-LD.
 *   - `notFound`  — backend said 404; the caller should `notFound()` so the
 *                   URL returns a real HTTP 404 and gets de-indexed.
 *   - `unavailable` — transient infra failure (rate-limit 429, 5xx, network).
 *                   The caller must NOT 500 and must NOT 404: render the
 *                   client component with generic metadata so the page still
 *                   serves a 200 and the browser loads the data itself.
 *
 * Why this exists: the marketplace SSR fetches hit the backend over the
 * internal network from a single container IP, so they share one anonymous
 * per-IP rate-limit bucket. A burst (crawler, Lighthouse, fast browsing)
 * trips a 429, which previously became a hard 500 on the model page and a
 * spurious 404 on the seller page. A 200 with client-loaded content beats
 * both. Transient statuses get a short bounded retry first.
 */

export type SsrFetchResult<T> =
  | { status: "ok"; data: T }
  | { status: "notFound" }
  | { status: "unavailable" };

// Statuses worth a brief retry — they signal "try again", not "wrong request".
const TRANSIENT_STATUSES = new Set([429, 500, 502, 503, 504]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

interface SsrFetchOptions {
  /** ISR revalidation window in seconds (passed to Next's fetch cache). */
  revalidate?: number;
  /** Number of extra attempts after the first on a transient failure. */
  retries?: number;
  /** Base backoff in ms; attempt N waits backoffMs * N. */
  backoffMs?: number;
  /** Label for SSR-log lines so failures are greppable. */
  label?: string;
}

/**
 * Fetch JSON for an SSR page, classifying the outcome for graceful SEO degradation.
 * Never throws — a thrown SSR fetch is exactly what turns a backend hiccup into a 500.
 */
export async function ssrJsonFetch<T>(
  url: string,
  { revalidate = 60, retries = 1, backoffMs = 200, label = "ssrJsonFetch" }: SsrFetchOptions = {},
): Promise<SsrFetchResult<T>> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    let res: Response;
    try {
      res = await fetch(url, { next: { revalidate } });
    } catch (err) {
      // Network-level failure (proxy down, DNS, connection reset).
      if (attempt < retries) {
        await sleep(backoffMs * (attempt + 1));
        continue;
      }
      console.error(`[${label}] fetch failed`, {
        url,
        error: err instanceof Error ? err.message : String(err),
      });
      return { status: "unavailable" };
    }

    if (res.status === 404) return { status: "notFound" };

    if (res.ok) {
      try {
        return { status: "ok", data: (await res.json()) as T };
      } catch (err) {
        console.error(`[${label}] JSON parse failed`, {
          url,
          error: err instanceof Error ? err.message : String(err),
        });
        return { status: "unavailable" };
      }
    }

    if (TRANSIENT_STATUSES.has(res.status) && attempt < retries) {
      await sleep(backoffMs * (attempt + 1));
      continue;
    }

    console.error(`[${label}] non-ok response`, { url, status: res.status });
    return { status: "unavailable" };
  }

  return { status: "unavailable" };
}
