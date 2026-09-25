import type { TriggerRun } from "@/lib/types";

/**
 * What the Webhook column says about one run.
 *
 * - `delivered`: the endpoint answered 2xx.
 * - `failed`: every attempt failed and the retries are spent.
 * - `not_sent`: the server refused to call the address (private, loopback or
 *   link-local), so nothing was attempted.
 * - `retrying`: some attempts failed and another one is scheduled.
 * - `none`: nothing has been attempted yet.
 *
 * `webhook_delivered` stays null while retries remain. The column showed "—"
 * for a run whose webhook had already failed three times (QA, 2026-09-25).
 */
export type WebhookState =
  | { kind: "delivered"; attempts: number }
  | { kind: "failed"; attempts: number }
  | { kind: "not_sent" }
  | { kind: "retrying"; attempts: number }
  | { kind: "none" };

export function webhookState(
  run: Pick<TriggerRun, "webhook_delivered" | "webhook_attempts">,
): WebhookState {
  const attempts = run.webhook_attempts ?? 0;
  if (run.webhook_delivered === true) return { kind: "delivered", attempts };
  if (run.webhook_delivered === false) {
    return attempts > 0 ? { kind: "failed", attempts } : { kind: "not_sent" };
  }
  return attempts > 0 ? { kind: "retrying", attempts } : { kind: "none" };
}

/**
 * Whether Rerun is offered for a run.
 *
 * Not for a run whose input was refused. The same input is refused again, and
 * each click used to record one more refused run. The server refuses such a
 * rerun too; the button is not offered so nobody is invited to try.
 */
export function canRerun(run: Pick<TriggerRun, "status">): boolean {
  return run.status !== "validation_failed";
}
