/**
 * Call `tick` every `intervalMs`, never twice at the same time.
 *
 * A `setInterval` with an async body sends the next request while the last
 * one is still out. The API client retries a 5xx after 1 s and then 2 s, so
 * during a backend blip a 1-second poll had three or four requests open at
 * once, and a "give up after N failures" counter counted all of them.
 *
 * `tick` handles its own errors; a rejection here is dropped so that one bad
 * tick does not stop the ones after it.
 *
 * Returns the function that stops the polling.
 */
export function pollEvery(
  tick: () => Promise<unknown>,
  intervalMs: number,
  { immediately = false }: { immediately?: boolean } = {},
): () => void {
  let inFlight = false;
  const run = () => {
    if (inFlight) return;
    inFlight = true;
    Promise.resolve()
      .then(tick)
      .catch(() => undefined)
      .finally(() => {
        inFlight = false;
      });
  };
  if (immediately) run();
  const id = setInterval(run, intervalMs);
  return () => clearInterval(id);
}
