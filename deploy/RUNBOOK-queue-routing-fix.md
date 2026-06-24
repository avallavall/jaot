# Queue Routing Fix - Operator Runbook (Phase 10 v2.2)

**Scope:** Operationalizes the production
rollout of the `default`-queue purge, the `celery` → `jaot_default` rename, and the manual
replay of the three idempotent daily tasks. The locked decisions are
**D-01**, **D-02**, **D-03**. Source of truth for the routing config that lands
in this deploy: plan `10-01` (code rename) + plan `10-02` (boot-time queue audit + Prometheus
alert + integration test). Bug provenance: the **F1** carry-out follow-up
— the Phase-9 bandaid that landed in commit `8dfc752f` (2026-05-18)
routed `send_contact_email` to `"celery"` to clear the inbox-blocker while leaving 112+
financial / cron / hexaly tasks orphaned in the unused `default` queue. This runbook drains
that backlog and ships the permanent fix.

**Production target:** the server, IP `<SERVER_IP>`. SSH user: `jaot`.
SSH key: `~/.ssh/id_ed25519_ci`. Deploy directory on the server: `/opt/jaot`. Production database:
`jaot` on the same Postgres instance as `jaot_test`. All `docker compose` invocations use
`-f /opt/jaot/deploy/docker-compose.prod.yml --env-file .env.production`. Container names
referenced below (verified against `deploy/docker-compose.prod.yml`):
`jaot_prod_rabbitmq`, `jaot_prod_api`, `jaot_prod_celery_default`, `jaot_prod_prometheus`.

**Subsystem invariants (do not violate without a deploy):**

- The post-Phase-10 generic Celery queue is named `jaot_default` (was `celery`). Both the
  Python producer config (`app/shared/core/celery_app.py` `task_default_queue`) and the
  consumer `-Q` flag in compose reference the single string `jaot_default`.
- The unused `default` queue MUST NOT exist after this procedure completes successfully.
  If it reappears, the boot-time audit shipped in plan `10-02` is bypassed or a producer
  has been re-introduced — STOP and read `app/shared/core/celery_app.py`.
- The ONLY tasks safe to manually re-fire after the purge are the three idempotent dailies
  named in **D-02**: `process_scheduled_withdrawals`, `run_balance_reconciliation`,
  `hexaly_platform_license_expiry_sweep`. Every other task in the purged `default` queue
  (user-triggered emails, webhooks, on-demand financial operations) is accepted as
  data-integrity cost per **D-01** — replay-spam risk on non-verified-idempotent tasks
  outweighs the benefit of replaying ~37 days of stale fires.

---

### Table of Contents

1. [Pre-flight checks](#1-pre-flight-checks)
2. [Purge the orphan `default` queue (BEFORE deploy)](#2-purge-the-orphan-default-queue-before-deploy)
3. [Deploy the code fix (plan 10-01 + 10-02)](#3-deploy-the-code-fix-plan-10-01--10-02)
4. [Verify worker is GREEN on `jaot_default`](#4-verify-worker-is-green-on-jaot_default)
5. [Drain or purge the legacy `celery` queue](#5-drain-or-purge-the-legacy-celery-queue)
6. [Manual replay: 3 idempotent dailies (D-02)](#6-manual-replay-3-idempotent-dailies-d-02)
7. [Post-procedure sign-off](#7-post-procedure-sign-off)

---

## 1. Pre-flight checks

**SSH connectivity probe** (operator workstation → the server):

```bash
ssh -i ~/.ssh/id_ed25519_ci jaot@<SERVER_IP> 'echo ok'
```

Expected: `ok`. Anything else → STOP, fix SSH before continuing. The `rabbitmqctl purge`
commands below are destructive — running them blind via half-broken SSH is the #1 risk.

**Confirm RabbitMQ management CLI reachable on the server:**

```bash
ssh jaot@<SERVER_IP> 'docker exec jaot_prod_rabbitmq rabbitmqctl list_queues name messages | head -20'
```

Expected: a list including `default <some-large-number>` (the orphan; ~112 messages or more
at time of writing — count grew daily while the bug was latent) and `celery <some-small-number>`
(the Phase-9 bandaid queue; may be empty or hold in-flight contact emails). Solver queues
(`solve_scip`, `solve_highs`, `solve_hexaly`) are unaffected by this procedure — leave them
alone.

**Capture pre-state evidence:**

```bash
ssh jaot@<SERVER_IP> 'docker exec jaot_prod_rabbitmq rabbitmqctl list_queues name messages \
  > /tmp/pre-purge-queues-$(date -u +%Y%m%dT%H%M%SZ).txt && \
  ls -la /tmp/pre-purge-queues-*.txt | tail -1'
```

Expected: a single file in `/tmp/` on the server containing the snapshot of queue names + depths.
This file is the rollback reference if anything goes wrong in §2 or §3 — record its full
path in the §7 sign-off table.

**Confirm CI is GREEN for the commits that ship plans 10-01 + 10-02:**

```bash
ssh jaot@<SERVER_IP> 'cd /opt/jaot && git log --oneline -10'
```

Expected: the top of the log shows the Plan 10-01 commit(s) (the `refactor(10-01)` Task 1
commit `fce9ffb3` + the Task 2 compose commit `4370e8ed` + the `docs(10-01)` SUMMARY commit)
and the Plan 10-02 commits (boot-time audit + alert rule + integration test). If CI
is still building the GHCR images, wait — do NOT pull mid-build.

---

## 2. Purge the orphan `default` queue (BEFORE deploy)

**Per D-01 (locked):** drop all messages in the unused `default` queue without processing
them. Tasks lost in the purge are accepted as the data-integrity cost of the original bug.
This step runs BEFORE the code deploy (D-03 step 1) so the queue is empty when the new
worker boots — that way, if the boot-time audit (plan 10-02) ever fires on a stale `default`
queue declaration, it does so on a known-empty broker state, not on 112+ accumulated rows.

**Capture the pre-purge count** (will be recorded in the §7 sign-off):

```bash
ssh jaot@<SERVER_IP> \
  'docker exec jaot_prod_rabbitmq rabbitmqctl list_queues name messages | grep "^default[[:space:]]"'
```

Expected: a single line like `default       112` (whitespace-delimited; count varies).

**Purge the queue:**

```bash
ssh jaot@<SERVER_IP> 'docker exec jaot_prod_rabbitmq rabbitmqctl purge_queue default'
```

Expected output: `Purging queue 'default' in vhost '/' ...` (and `done` or silent return
depending on rabbitmqctl version). Anything else (error, "no queue named", non-zero exit) →
STOP and inspect — the queue name passed to `purge_queue` is a literal, no shell expansion,
so a typo is the only reasonable failure mode here.

**Verify the queue is empty:**

```bash
ssh jaot@<SERVER_IP> \
  'docker exec jaot_prod_rabbitmq rabbitmqctl list_queues name messages | grep "^default[[:space:]]"'
```

Expected: `default       0` (or the queue may be absent — both outcomes mean the purge
succeeded). If the count is still > 0, there is a producer still enqueueing to `default`
right now (which means plan 10-01 has not deployed yet — check §3 first) — re-run the
purge after §3 completes.

**Record the purged count** in the §7 sign-off log. This is the only audit trail of the
data-integrity cost paid by D-01.

---

## 3. Deploy the code fix (plan 10-01 + 10-02)

**Pre-conditions:** Plan 10-01 (routing config rename) and plan 10-02 (boot-time audit +
Prometheus alert + integration test) have merged to `main`. CI has pushed fresh
images (`jaot-api`, `jaot-worker`) to GHCR. The `default` queue is empty (§2 just ran).

**Standard rotation — recreate only the impacted services:**

```bash
ssh jaot@<SERVER_IP> 'cd /opt/jaot && git pull && \
  docker compose -f deploy/docker-compose.prod.yml --env-file .env.production pull && \
  docker compose -f deploy/docker-compose.prod.yml --env-file .env.production \
    up -d celery_worker_default api beat'
```

Why only these three: `celery_worker_default` carries the `-Q jaot_default` rename
(plan 10-01) + the boot-time audit (plan 10-02); `api` carries the matching producer config
in `app/shared/core/celery_app.py`; `beat` carries the renamed `beat_schedule[*].options.queue`
entries. Solver workers (`celery_worker_scip`, `celery_worker_highs`, `celery_worker_hexaly`)
are untouched by this phase — leave them alone to avoid unnecessary churn.

**Boot-time audit guarantee (plan 10-02).** The new worker process will run the
queue-coherence audit inside `worker_process_init` BEFORE consuming a single task. If any
referenced queue (from `task_routes`, `beat_schedule[*].options.queue`, or
`task_default_queue`) is NOT in the worker's `-Q` flag, the worker logs CRITICAL and
exits non-zero. This is a **feature, not a bug** — a stuck container after this deploy is
the system telling you the producer and consumer configs drifted again. If that happens,
inspect:

```bash
ssh jaot@<SERVER_IP> 'docker logs --tail 200 jaot_prod_celery_default'
```

On success, the logs include a line indicating the audit passed (exact text per plan 10-02
implementation). On failure, the logs include a CRITICAL line naming the offending queue
and the producer that references it — read it, then `git diff` against the previous deploy
to find the regression. Do NOT mask the failure by adding the missing queue to `-Q`
defensively — that's the bug-shape **D-06** rejected.

**Wait for the new worker to settle.** Allow ~30 seconds after `docker compose up -d` for
the boot-time audit to run and the worker to begin consuming. Proceed to §4 only after the
container shows healthy.

---

## 4. Verify worker is GREEN on `jaot_default`

**Inspect active queues from inside the new worker container:**

```bash
ssh jaot@<SERVER_IP> \
  'docker exec jaot_prod_celery_default celery -A app.shared.core.celery_app inspect active_queues'
```

Expected: a YAML-ish block for the `celery@jaot_prod_celery_default` node, including a queue
named `jaot_default`. Critically, the output MUST NOT include `default` or `celery` as
active queues for this node — if either appears, the `-Q` flag in compose was not updated
(plan 10-01 Task 2 regression) or the container was not recreated (re-run §3 `docker compose
up -d --force-recreate celery_worker_default`).

**Cross-check via Prometheus celery-exporter** (the exporter is deployed in Phase 6.1 as
`jaot_prod_celery_exporter`; it exposes per-queue depth as `celery_queue_length{queue_name="..."}`.
Note: the built-in RabbitMQ Prometheus exporter at `rabbitmq:15692` only exposes aggregate
`rabbitmq_queue_messages` without a per-queue label, so it cannot satisfy these queries —
2026-05-19 Phase 10 deploy verified celery-exporter is the right source):

```bash
ssh jaot@<SERVER_IP> \
  'curl -sf "http://localhost:9090/api/v1/query?query=celery_queue_length{queue_name=\"jaot_default\"}" \
   | jq ".data.result | length"'
```

Expected: `>= 1` (the gauge is registered as soon as the queue exists). If `0`, Prometheus
has not scraped the exporter yet (wait 30s and retry) OR the queue was never declared by
the new worker (which means the worker is not actually running — re-read §3 logs).

**Confirm the old `default` queue is gone or empty:**

```bash
ssh jaot@<SERVER_IP> \
  'curl -sf "http://localhost:9090/api/v1/query?query=celery_queue_length{queue_name=\"default\"}" \
   | jq ".data.result"'
```

Expected: a single result with `value` ≈ `"0"` (post-purge, queue declared but empty). If
the value is anything other than 0, a producer somewhere still references `'default'` —
STOP and `grep -r '\"default\"' app/` to find it. This must NOT proceed to §5 until the
`default` queue is provably idle.

**Note on the Prometheus alert from plan 10-02.** Plan 10-02 adds a queue-depth alert
(`celery_queue_length{queue_name="..."} > 50 for 30m`) that will catch any future
regression of this exact bug-shape (mountain of unconsumed messages). The alert is loaded
as part of this deploy; verify with:

```bash
ssh jaot@<SERVER_IP> 'curl -sf http://localhost:9090/api/v1/rules \
  | jq ".data.groups[] | select(.name | contains(\"queue\") or contains(\"async\")) | .rules | length"'
```

Expected: `>= 1` (the exact group name and rule count depend on plan 10-02's final
implementation; the assertion is "the rule loaded, not zero").

---

## 5. Drain or purge the legacy `celery` queue

**Context.** The Phase-9 bandaid (commit `8dfc752f`) routed `send_contact_email` to a
`"celery"` queue so the `celery_worker_default` service — which at the time consumed `-Q celery`
— could deliver inbox emails. Plan 10-01 removed that explicit `task_routes` entry (the
contact task now inherits the renamed default `jaot_default`) and plan 10-01 also flipped
the worker's `-Q` flag from `celery` to `jaot_default`. At this point in the procedure,
producers no longer enqueue to `"celery"` and no consumer subscribes to it. Anything still
in the legacy `celery` queue is an in-flight Phase-9-era contact-form email that was
mid-flight when §3 deployed.

**Quick count of what's left in the legacy queue:**

```bash
ssh jaot@<SERVER_IP> \
  'docker exec jaot_prod_rabbitmq rabbitmqctl list_queues name messages | grep "^celery[[:space:]]" || echo "queue absent"'
```

Three possible outcomes:

- `queue absent` (or grep returns empty + the literal `queue absent`) → the legacy queue
  was already auto-cleaned at the broker level. **Nothing to do.** Skip to §6.
- `celery       0` → queue declared but empty. **Nothing to do.** The queue will be
  cleaned up on the next RabbitMQ container restart. Skip to §6.
- `celery       <N>` with N > 0 → choose drain OR purge below.

**Option A — Drain** (preferred if the in-flight emails are real customer messages that
matter). Start an ephemeral foreground worker that subscribes to ONLY the legacy queue,
consume until empty, Ctrl-C:

```bash
ssh -t jaot@<SERVER_IP> \
  'docker run --rm --network jaot_prod_backend \
     -e CELERY_BROKER_URL="amqp://jaot:jaot@rabbitmq:5672//" \
     --env-file /opt/jaot/.env.production \
     ghcr.io/avallavall/jaot-worker:latest \
     celery -A app.shared.core.celery_app worker -Q celery --loglevel=info --concurrency=1'
```

This is the ONE place this runbook uses a TTY (`-t`) — the operator runs the ephemeral
worker in the foreground, watches it consume, and presses Ctrl-C when the queue empties.
The `--rm` flag ensures no residue. Maximum runtime: ~60 seconds (the queue size is
bounded; if it does not empty in 60s, something else is wrong).

**Note on hardcoded credentials (WR-02):** the `amqp://jaot:jaot@...` literal above is the
production RabbitMQ user/password (matches `RABBITMQ_USER=jaot` / `RABBITMQ_PASS=jaot` in
`.env.production`). The previous form `amqp://${RABBITMQ_USER:-jaot}:${RABBITMQ_PASS:-jaot}@...`
was inside single-quoted SSH and would NOT expand on the remote host — it would interpolate
against the operator's remote shell env (where these vars are NOT set), silently falling
back to the `:-jaot` defaults. If a future production deploy rotates the RabbitMQ
credentials, update this literal AND `.env.production` together. The `--env-file` flag
already passes the credential into the container's environment for the Celery worker
process; the `-e CELERY_BROKER_URL=...` is only used to give the worker its broker URL at
process-start time.

**Option B — Purge** (acceptable if the in-flight emails are stale and the operator decides
they no longer matter — e.g., if the §1 timestamp is hours after the last legitimate contact-
form submission). Single command, destructive:

```bash
ssh jaot@<SERVER_IP> 'docker exec jaot_prod_rabbitmq rabbitmqctl purge_queue celery'
```

Same expected output as the §2 purge (`Purging queue 'celery' in vhost '/' ...`). Record
the count purged in §7 just like the §2 default-queue purge.

**Operator's call.** Drain is preferred when contact-form volume is non-zero in the last
24h (the visitor expects their message to arrive). Purge is acceptable when the operator
is confident no recent contact submissions are stuck — e.g., the smoke test from
`deploy/RUNBOOK-contact-form.md` § 2 was last run hours ago and returned `status='sent'`
for all rows.

---

## 6. Manual replay: 3 idempotent dailies (D-02)

**Per D-02 (locked):** before considering the system recovered, manually fire ONE fresh
execution of each of the three idempotent daily tasks. Rationale per task:

- `process_scheduled_withdrawals` — there may be `WithdrawalSchedule` records with
  `next_execution <= now()` that accumulated during the 37-day bug window. The service's
  idempotency guards (`app/tasks/financial_tasks.py` and
  `CreditsService.process_scheduled_withdrawals`) prevent double-execution; safe to re-fire.
- `run_balance_reconciliation` — `ReconciliationService.run_reconciliation` is read-mostly
  and writes only alert events on drift. Safe to re-run; brings the daily reconciliation
  state to today.
- `hexaly_platform_license_expiry_sweep` — refreshes the
  `jaot_hexaly_platform_license_days_remaining` Prometheus gauge to today's days-remaining
  value. The 24h notification dedup (Phase 7 E-12) prevents alert-storm even if the gauge
  trips the < 30 days threshold.

**Replay command (run once per task).** All three replays go through the helper script
`deploy/scripts/replay-daily-task.sh`, which takes the task name as `$1` and exits non-zero
if it's missing. This replaces the previous inline `docker exec ... python -c "..."` form,
whose triple-nested quoting (single-quoted SSH arg + double-quoted `python -c` + escaped
double-quoted task name) was brittle to operator copy-paste between shells (IN-03):

```bash
ssh jaot@<SERVER_IP> \
  'docker exec jaot_prod_api bash /opt/jaot/deploy/scripts/replay-daily-task.sh process_scheduled_withdrawals'
```

Expected: a single line containing a Celery task id (UUID-like). Record it for §7. Repeat
for the other two task names:

```bash
ssh jaot@<SERVER_IP> \
  'docker exec jaot_prod_api bash /opt/jaot/deploy/scripts/replay-daily-task.sh run_balance_reconciliation'
```

```bash
ssh jaot@<SERVER_IP> \
  'docker exec jaot_prod_api bash /opt/jaot/deploy/scripts/replay-daily-task.sh hexaly_platform_license_expiry_sweep'
```

**Verify all three were consumed by the new worker:**

```bash
ssh jaot@<SERVER_IP> \
  'docker logs --tail 200 jaot_prod_celery_default | grep -E "(process_scheduled_withdrawals|run_balance_reconciliation|hexaly_platform_license_expiry_sweep)"'
```

Expected: three matching task ids (the same UUIDs printed above) with INFO log lines ending
in `succeeded` (or `Task ... succeeded in ...`). If any task shows `FAILED` or never
appears in the log, the new worker is not consuming `jaot_default` — re-read §4 verification
and §3 logs. Do NOT re-fire a failed task without first understanding why it failed (one
of the three is `process_scheduled_withdrawals`, which moves money — debug before re-firing).

**Note on bypassing beat.** This manual replay short-circuits the beat scheduler — beat
will still fire all three tasks at their next 24h tick. That's intentional: the manual
replay's goal is to surface today's state immediately, not to perturb the schedule.

---

## 7. Post-procedure sign-off

Fill in this table at the end of the procedure. The completed table is the audit trail —
it lives in this runbook (operator commits an inline update) OR in the closure document
for Phase 10 (operator records the timestamp + initials, no need to inline the runbook
itself).

| Field | Value |
|-------|-------|
| Pre-purge `default` queue count (§1 evidence file) | `<N>` (from `/tmp/pre-purge-queues-*.txt`) |
| Post-purge `default` queue count (§2 verify) | `0` (or queue absent) |
| Worker container restart timestamp (§3) | `<UTC>` |
| `jaot_default` queue first-seen in Prometheus (§4) | `<UTC>` |
| Legacy `celery` queue disposition (§5) | `drained` / `purged` / `empty` (pick one) |
| Legacy `celery` count drained or purged | `<M>` (or `0`) |
| Replay task id — `process_scheduled_withdrawals` (§6) | `<task-id>` |
| Replay task id — `run_balance_reconciliation` (§6) | `<task-id>` |
| Replay task id — `hexaly_platform_license_expiry_sweep` (§6) | `<task-id>` |
| Boot-time audit log line observed (§3 plan 10-02) | `yes` / `no` |
| Prometheus queue-depth alert rule loaded (§4) | `yes` / `no` |

**Sign-off line:**

```
Operator: <initials> at <UTC timestamp>; Phase 10 deploy + replay complete.
References: D-01 (purge default), D-02 (3-task replay), D-03 (5-step sequence).
Plan commits deployed: <list of SHAs for plan 10-01 and plan 10-02 from `git log` in §1>.
```

---

## Rollback

If §3 deploy fails the boot-time audit (worker exits non-zero) and the cause is not
immediately obvious, revert is fast — no destructive schema changes shipped in this phase:

```bash
ssh jaot@<SERVER_IP> 'cd /opt/jaot && git log --oneline -10 \
  | grep -E "(refactor\(10-01\)|feat\(10-02\))" | head -3'
```

Identify the three commit SHAs to revert (Task 1 + Task 2 of plan 10-01, plus the plan
10-02 implementation commits). Then:

```bash
ssh jaot@<SERVER_IP> 'cd /opt/jaot && \
  git revert --no-edit <sha1> <sha2> <sha3> && \
  docker compose -f deploy/docker-compose.prod.yml --env-file .env.production pull && \
  docker compose -f deploy/docker-compose.prod.yml --env-file .env.production \
    up -d --force-recreate celery_worker_default api beat'
```

This reverts the source-tree changes; CI will rebuild on the next push, but for an
emergency rollback the pulled GHCR `latest` images may still contain the old code (the
revert lands in the next CI cycle). For an immediate rollback to the pre-Phase-10 image
SHAs, pin to a known-good GHCR digest in `.env.production` (`API_IMAGE`,
`CELERY_WORKER_IMAGE`) — the SHAs from the Phase-9-closure commit `83c3aecc` are the
last-known-good for this purpose.

**Post-rollback:** the `default` queue stays empty (the §2 purge already happened and the
producers in the reverted code re-enqueue to `default`, so it'll refill — that's the
pre-Phase-10 broken state, which is what "rollback" means here). Re-run §2 purge if the
revert is intended to be left in place for > 24h, otherwise plan a fresh forward-deploy
attempt.

---

### Cross-references

- `deploy/RUNBOOK-contact-form.md` — Phase 9 runbook (same SSH host / compose conventions /
  prose tone). Mirrored for §2 verify-after-deploy patterns.
- `app/shared/core/celery_app.py` lines 60-74 — comment block describing the boot-time
  audit invariant introduced by plan 10-02.
- `monitoring/prometheus/alert_rules.yml` — queue-depth alert from plan 10-02.
