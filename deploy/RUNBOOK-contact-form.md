# Contact Form — Operator Runbook (Phase 9 v2.2)

**Scope:** Operates the public `/contact`
subsystem on the JAOT production host — daily checks, alert response, GDPR delete handling,
and retention.
Source of truth for the alert rule definitions: `monitoring/prometheus/alert_rules.yml`
(group `contact_form`). Precedent runbook style (terse, command-first, two human-action
sections called out): `deploy/RUNBOOK-plausible.md`.

**Production target:** the server, IP `<SERVER_IP>`. SSH user: `jaot`.
SSH key: `~/.ssh/id_ed25519_ci`. Deploy directory on the server: `/opt/jaot`. Production database:
`jaot` on the same Postgres instance as `jaot_test`. All `docker compose` invocations use
`-f /opt/jaot/deploy/docker-compose.prod.yml --env-file .env.production`.

**Subsystem invariants (do not violate without a deploy):**

- `POST /api/v2/contact` is in `PUBLIC_PATHS` (anonymous-friendly, opportunistic JWT).
- Anti-spam guard: honeypot (`website` field) + 3 / 15-min + 10 / day per-IP rate-limits
  (D-01, D-02). No CAPTCHA in v1 (D-01); see §4 for the promotion criterion.
- Delivery: synchronous DB-store then async Celery `send_contact_email` with
  max_retries=5 and exponential backoff 60→120→240→480→960s (D-04).
- Recipient: PSS key `CONTACT_RECIPIENT` (default `admin@jaot.io`), runtime-editable (D-07).
- Persistence is additive-only — never `DROP TABLE contact_messages` as part of a release;
  schema rollback is a destructive operation reserved for unrecoverable corruption (§8).

---

### Table of Contents

1. [Daily operations](#1-daily-operations)
2. [Verify end-to-end after deploy](#2-verify-end-to-end-after-deploy)
3. [Alert response — `ContactFormDeliveryFailing`](#3-alert-response)
4. [Spam surge response — `ContactFormSpamSurge`](#4-spam-surge-response)
5. [GDPR delete-on-request](#5-gdpr-delete-on-request)
6. [Retention policy](#6-retention-policy)
7. [Configuration reference](#7-configuration-reference)
8. [Decommission / rollback](#8-decommission--rollback)

---

## 1. Daily operations

**View the 20 most recent submissions** (from any operator box with SSH access to the server):

```bash
ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
  exec -T postgres psql -U jaot -d jaot -c "
    SELECT id, created_at, status, name, email, subject, attempts
    FROM contact_messages
    ORDER BY created_at DESC
    LIMIT 20;
  "'
```

Columns interpretation:
- `status` ∈ `pending` (Celery task enqueued, not yet picked up), `sent` (SMTP delivery
  succeeded, `sent_at` populated), `failed` (terminal exhaustion after 5 retries — see §3).
- `attempts` is the authoritative counter (incremented before each send try).

**View Celery worker logs for the last 24h, filtered to contact:**

```bash
ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
  logs --since 24h celery_worker_default | grep -E "contact_(submission|send_attempt|messages|email)"'
```

The grep pattern matches both `contact_submission` (route emissions) and
`contact_send_attempt` (task emissions). Both lines carry `message_id` + `result` (and never
`name`/`email`/`subject`/`body` — T-09-09 mitigation).

**PSS keys to know about:**

- `CONTACT_RECIPIENT` (default `admin@jaot.io`) — recipient mailbox; change via admin panel
  at `/admin/settings`. Takes effect on the next Celery task execution (no redeploy).
- `EMAIL_BACKEND` (`smtp` in prod, `console` in dev) — controls whether `EmailService.send`
  actually transmits. If you accidentally set this to `console` in prod, emails will be
  written to stdout instead of sent.

**Prometheus metrics to inspect:**

```bash
# From the server (Prometheus listens on localhost only):
curl -sf 'http://localhost:9090/api/v1/query?query=jaot_contact_message_send_attempts_total' | jq .
curl -sf 'http://localhost:9090/api/v1/query?query=jaot_contact_spam_blocked_total' | jq .
```

Counter label vocabulary (closed; validated by
`tests/integration/api/v2/test_contact_observability.py::test_alert_rule_label_selector_matches_counter`):

- `jaot_contact_message_send_attempts_total.result` ∈ `{sent, retry, failed}`
- `jaot_contact_spam_blocked_total.reason` ∈ `{honeypot, rate_limit_minute, rate_limit_day, validation}`

---

## 2. Verify end-to-end after deploy

This is the canonical post-deploy smoke procedure. All 5 steps MUST
pass before the deploy is considered green.

**Step 1 — Anonymous happy path:**

```bash
curl -sf -X POST https://jaot.io/api/v2/contact \
  -H 'Content-Type: application/json' \
  -d '{"name":"Smoke","email":"smoke@example.com","subject":"deploy smoke","message":"verifying"}' \
  | jq .id
```

Expected: a `ctc_*` id (the public contact id). Anything else → STOP, the endpoint is broken;
read `docker compose logs api` for the immediate exception.

**Step 2 — Inbox check (manual, mailbox-dependent):**

Within ~60 seconds, the configured `CONTACT_RECIPIENT` mailbox receives an email with:
- `Subject: [JAOT Contact] deploy smoke`
- `Reply-To: Smoke <smoke@example.com>` (clicking Reply in the mail client addresses the
  visitor directly without copy-paste — D-09).
- Body first line: `Locale: en` (or whatever locale the visitor's browser advertised).

If the email does not arrive within 60s, jump to §3 (alert response) — the task is either
queued/stuck or hit a terminal `failed` immediately.

**Step 3 — DB confirmation:**

```bash
ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
  exec -T postgres psql -U jaot -d jaot -c "
    SELECT status, sent_at FROM contact_messages WHERE id='\''<the-id-from-step-1>'\'';
  "'
```

Expected: `status='sent'`, `sent_at` populated (within ~60s of the POST).

**Step 4 — Honeypot smoke (verifies the anti-spam guard fires):**

```bash
curl -s -X POST https://jaot.io/api/v2/contact \
  -H 'Content-Type: application/json' \
  -d '{"name":"S","email":"s@e.com","subject":"x","message":"y","website":"http://spam"}' \
  -o /dev/null -w '%{http_code}\n'
```

Expected: `400`. Anything else means the honeypot bypass risk is no longer accepted — STOP
and re-verify D-01 / `app/api/v2/contact.py` was deployed correctly.

**Step 5 — Metric scrape sanity:**

```bash
ssh jaot@<SERVER_IP> \
  'curl -sf "http://localhost:9090/api/v1/query?query=jaot_contact_message_send_attempts_total" \
   | jq ".data.result | length"'
```

Expected: `>= 1`. If `0` → the counter is registered but Prometheus has not scraped a value
yet (wait 30s and retry) OR the api container is failing to expose `/metrics` (read
`docker compose logs api`).

---

<a name="3-alert-response"></a>

## 3. Alert response — `ContactFormDeliveryFailing`

**Trigger:** `increase(jaot_contact_message_send_attempts_total{result="failed"}[1h]) > 0`,
`for: 5m`. Defined in `monitoring/prometheus/alert_rules.yml` group `contact_form`.

**Meaning:** at least one `contact_messages` row has reached terminal `status='failed'` in
the last hour — i.e. it exhausted all 5 retries (D-04) and `_send_failure_notification`
fired (best-effort admin email).

**Investigation procedure:**

1. **Pull failed rows** (last 20):

   ```bash
   ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
     exec -T postgres psql -U jaot -d jaot -c "
       SELECT id, created_at, attempts, left(last_error, 200) AS last_error
       FROM contact_messages
       WHERE status='\''failed'\''
       ORDER BY created_at DESC
       LIMIT 20;
     "'
   ```

   The `last_error` column carries the exception name + message (truncated to 1000 chars
   on write).

2. **Inspect `last_error` — common patterns:**

   - `SMTPException: 5xx ...` → SMTP credentials, sender, or recipient rejected. Verify
     `EMAIL_BACKEND`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS` in admin
     panel `/admin/settings` (Email category).
   - `SMTPException: 4xx ...` → transient; should have retried 5×. If still failing on
     fresh attempts, the SMTP server may be deny-listing the JAOT IP — check the SMTP
     provider's reputation dashboard.
   - `OSError: [Errno ...] ...` → network/DNS issue between the worker and SMTP host.
     Check the server's network from inside the worker container:
     `docker compose exec celery_worker_default getent hosts <SMTP_HOST>`.

3. **Manual replay** of a single failed row (after fixing the underlying cause):

   ```bash
   ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
     exec celery_worker_default celery -A app.shared.core.celery_app \
     call app.tasks.contact_tasks.send_contact_email --args='\''["<the-id>"]'\'''
   ```

   The task will re-attempt delivery and (if successful) flip `status` back to `sent`.
   Note: `attempts` does NOT reset — it keeps climbing. If the row has already crossed
   `max_retries`, the manual call still attempts once (the terminal-failure check uses
   `msg.attempts <= self.max_retries` and a manual `celery call` resets
   `self.request.retries` to 0).

4. **Wrong `CONTACT_RECIPIENT`?** If the failure is on the admin side (recipient mailbox
   does not exist, full quota, etc.), update the PSS key via admin panel at
   `/admin/settings` and rerun the replay. The Celery task reads the recipient at task
   execution time (D-07), so the change propagates immediately to subsequent retries.

5. **Silence the alert** during a known maintenance window: use Alertmanager's silence UI
   (accessible via the same SSH-tunnel pattern as Grafana). Default silence duration
   should match the maintenance window — never silence indefinitely.

---

<a name="4-spam-surge-response"></a>

## 4. Spam surge response — `ContactFormSpamSurge`

**Trigger:** `(sum(rate(jaot_contact_spam_blocked_total[1h])) / clamp_min(sum(rate(jaot_contact_message_send_attempts_total[1h])) + sum(rate(jaot_contact_spam_blocked_total[1h])), 1)) > 0.05`,
`for: 1h`. Defined in `monitoring/prometheus/alert_rules.yml` group `contact_form`.

**Meaning:** the spam-blocked fraction over the last hour exceeded 5% of total inbound
(send-attempts + blocked). This is the operationalized escalation criterion for the
captcha-promotion decision (D-01).

**Investigation procedure:**

1. **Break down the spam-blocked rate by reason:**

   ```bash
   ssh jaot@<SERVER_IP> 'curl -sf \
     "http://localhost:9090/api/v1/query?query=sum(rate(jaot_contact_spam_blocked_total[1h]))%20by%20(reason)" \
     | jq .data.result'
   ```

   Each entry is `{ "metric": { "reason": "honeypot" | "rate_limit_minute" | "rate_limit_day" | "validation" }, "value": [<timestamp>, "<rate>"] }`.

2. **Interpret the dominant reason:**

   - `reason="honeypot"` dominates → bots are filling the hidden `website` field; the
     guard is working. No action required unless the **inbox** also shows visible spam
     (i.e. honeypot is being bypassed by smarter bots — promote to captcha, see step 5).
   - `reason="rate_limit_minute"` or `"rate_limit_day"` dominates → sustained per-IP
     abuse. Pull the top offenders from the API logs:

     ```bash
     ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
       logs --since 1h api | grep -E "rate_limited" | sort | uniq -c | sort -nr | head -20'
     ```

     The `contact_submission` log line carries `ip_redacted` (last octet masked), which is
     enough to identify a /24 hammering pattern without storing full IPs. Consider an IP
     block at the Caddy layer (temporary) or escalate to Cloudflare Turnstile (step 5).

   - `reason="validation"` dominates → either a bot is probing the 422 schema OR a
     frontend bug is sending malformed bodies. Cross-check `validation_error` log lines
     (emitted by `contact_validation_exception_handler` per Plan 09-01 Task 2 step 3):

     ```bash
     ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
       logs --since 1h api | grep -E "validation_error" | head -50'
     ```

     The log line contains ONLY the field locations and Pydantic error type codes — never
     user-supplied values (T-09-09 PII-redaction). If the field locations are always the
     same field (e.g., always `["body", "email"]`), the frontend is probably sending an
     invalid payload — file a bug. If the locations are diverse, it's bot probing —
     proceed to step 5.

3. **Inspect the actual admin inbox.** The Prometheus surge alert is a signal, not a
   verdict — confirm the team is seeing real spam emails arrive. If the inbox is clean,
   the honeypot/rate-limit guards are catching everything and no escalation is needed
   (silence the alert with a one-week note explaining the situation).

4. **Bandwidth check.** Heavy spam can saturate the rate-limiter and degrade legitimate
   traffic. If genuine `accepted` submissions are dropping during the surge window,
   tighten the per-IP limits temporarily (edit `app/api/v2/contact.py`,
   `check_rate_limit_15min(..., 3)` and `check_rate_limit(..., limit_per_day=10)` —
   adjust and redeploy). This is intentionally a source-edit, not a PSS key — per D-02.

5. **Captcha promotion criterion (D-01):** if the 5% threshold persists for >24h AND the
   admin team confirms actual spam reaching the inbox (i.e., honeypot is bypassed),
   implement Cloudflare Turnstile (or hCaptcha as alternative). This was a deliberately
   deferred item — "Cloudflare Turnstile / hCaptcha". Phase 9 v1
   deliberately deferred this to keep MVP scope tight; the alert is the trigger to
   re-open it.

---

## 5. GDPR delete-on-request

T-09-06 mitigation. When a visitor emails `admin@jaot.io` (or the configured
`CONTACT_RECIPIENT`) requesting deletion of their submission, follow this procedure.

**Always run inside an explicit `BEGIN; ... COMMIT;` transaction.** Verify the `SELECT`
returns the expected rows BEFORE issuing the `DELETE`.

**Delete by single submission id** (preferred when the requestor cites a specific
ticket / reply thread):

```bash
ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
  exec -T postgres psql -U jaot -d jaot -c "
    BEGIN;
    SELECT id, email, created_at FROM contact_messages WHERE id = '\''ctc_xxx'\'';
    -- Verify the row matches the requestor — if yes, run the next line:
    DELETE FROM contact_messages WHERE id = '\''ctc_xxx'\'';
    COMMIT;
  "'
```

**Delete by email + age** (when the requestor cites only their email and asks for *all* old
submissions to be wiped):

```bash
ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
  exec -T postgres psql -U jaot -d jaot -c "
    BEGIN;
    SELECT id, created_at, status FROM contact_messages
    WHERE email = '\''visitor@example.com'\'' AND created_at < now() - interval '\''30 days'\'';
    -- Verify the rows match the requestor — if yes, run the next line:
    DELETE FROM contact_messages
    WHERE email = '\''visitor@example.com'\'' AND created_at < now() - interval '\''30 days'\'';
    COMMIT;
  "'
```

**Audit-trail note.** Postgres `DELETE` is destructive (no soft-delete column in v1 — by
design, per D-09 area). After commit, the only record of the deletion is the
PostgreSQL transaction log (`pg_wal`) which is rotated within days. If a stronger audit
record is required, copy the row contents into a separate "deletion log" before running
the DELETE — there is no built-in tool for this in Phase 9.

**Do NOT delete `status='pending'` rows.** Those represent in-flight Celery deliveries;
deleting one mid-flight will cause the task to log a "vanished" warning and increment
`CONTACT_SEND_ATTEMPTS{result="failed"}` (which can in turn page §3). If the requestor
cites a pending row, wait until the row reaches `sent` or `failed` (typically <30 min),
then delete.

---

## 6. Retention policy

Accepted-MVP risk (D-09 area + T-09-06 mitigation). Wave 2 promotes
T-09-06 from `accept` → `mitigate` by documenting both the manual delete procedure (§5)
and the retention schedule below.

**Warm storage** (live `contact_messages` table): keep 90 days. Anything older is a
candidate for the monthly sweep.

**Cold storage**: monthly `pg_dump` archive of the `contact_messages` table is preserved
as part of the standard daily DB backup that runs from
`deploy/scripts/backup-postgres.sh` (referenced by `deploy/RUNBOOK-disaster-recovery.md`).
Cold-storage retention follows the platform-wide 1-year rule (see DR runbook).

**Manual sweep** (operator-run; **NOT automated in v1** — by design):

```bash
ssh jaot@<SERVER_IP> 'docker compose -f /opt/jaot/deploy/docker-compose.prod.yml \
  exec -T postgres psql -U jaot -d jaot -c "
    BEGIN;
    SELECT COUNT(*) FROM contact_messages
    WHERE created_at < now() - interval '\''90 days'\''
      AND status IN ('\''sent'\'', '\''failed'\'');
    -- Verify the count is what you expect, then:
    DELETE FROM contact_messages
    WHERE created_at < now() - interval '\''90 days'\''
      AND status IN ('\''sent'\'', '\''failed'\'');
    COMMIT;
  "'
```

Recommended cadence: **monthly**, first business day. After each sweep, append a row to
`deploy/RUNBOOK-contact-form-retention-log.md` (operator creates the file on first run):

```
| date | rows deleted | operator | notes |
|------|--------------|----------|-------|
| 2026-05-01 | 14 | owner | first sweep — pre-existing rows from MVP |
```

**Rows EXCLUDED from the sweep:**

- `status='pending'` — in-flight, never touch (same reasoning as §5).
- Rows younger than 90 days (warm window).
- Rows explicitly preserved for an open conversation (manual override — comment in the
  retention log).

**Why no automation in v1.** A daily Celery beat sweep was rejected during planning
as a deferred item: the cost of mis-configuring a recurring DELETE
job is higher than the cost of a once-a-month manual run. When `contact_messages` volume
crosses ~10k rows/month, revisit and add automation.

---

## 7. Configuration reference

**PSS keys** (admin panel `/admin/settings`, Email category; defaults defined in
`app/services/settings_registry.py`):

| Key | Default | Description |
|-----|---------|-------------|
| `CONTACT_RECIPIENT` | `admin@jaot.io` | Recipient email for inbound contact-form messages. Runtime-editable; takes effect on next Celery task. |
| `EMAIL_BACKEND` | `smtp` (prod) | `console` (dev) or `smtp` (prod). MUST be `smtp` in prod or no email is actually sent. |
| `SMTP_HOST` | (prod-set) | SMTP server hostname. |
| `SMTP_PORT` | (prod-set) | SMTP server port (typically 587 for STARTTLS). |
| `SMTP_USER` | (prod-set) | SMTP authentication username. |
| `SMTP_PASSWORD` | (prod-set, secret) | SMTP authentication password. |
| `SMTP_USE_TLS` | `true` | STARTTLS enabled. |
| `SMTP_TIMEOUT` | `30` | Socket timeout in seconds. |

These SMTP keys are Phase 1F vintage — Phase 9 does NOT touch them. If SMTP delivery is
broken globally, the failure surface is wider than just /contact (e.g., signup welcome
emails would also fail) — investigate at the email-service tier.

**Rate-limit configuration** (hardcoded in `app/api/v2/contact.py`, per D-02):

- 3 submissions / 15 minutes per IP (`check_rate_limit_15min(..., 3)`)
- 10 submissions / day per IP (`check_rate_limit(..., limit_per_day=10)`)

To change either limit, edit the source and redeploy. This is intentionally NOT a PSS
key — abuse-control limits should require a code review, not an admin-panel toggle.

**Honeypot configuration:** the hidden `<input name="website">` field is rendered with
`display:none` + `tabindex={-1}` + `aria-hidden="true"`. Any non-empty `website` value on
the POST body trips the guard (400 response, `CONTACT_SPAM_BLOCKED{reason="honeypot"}`
counter increment, no DB write, no Celery enqueue). Honeypot bypass is an accepted MVP
risk per D-01; the captcha-promotion criterion in §4 step 5 is the operational trigger to
re-evaluate.

**Email-recipient context.** `CONTACT_RECIPIENT` is intentionally a JAOT-internal admin
address (`*@jaot.io`), NOT any personal operator email. Confirm with the team owner which
mailbox they want this routed to before each new deploy; the default
`admin@jaot.io` is a placeholder, not a commitment.

---

## 8. Decommission / rollback

**To temporarily disable submissions** without a schema rollback: remove the
`("/api/v2/contact", "POST")` entry from `PUBLIC_PATHS` in
`app/shared/core/auth_middleware.py` and redeploy. The endpoint will then return 401 for
all submissions, effectively disabling the form for anonymous users. Authenticated users
would still be able to submit — to disable for them too, also remove the
`router.include_router(contact.router, ...)` line in `app/api/v2/router.py`.

**Note:** this is intentionally NOT a PSS feature flag. There is no admin-panel kill
switch in v1, by design — toggling /contact on/off without a deploy trail is precisely
the kind of operator footgun we avoid in this codebase.

**To rollback the schema** (destructive — last resort):

```bash
ssh jaot@<SERVER_IP> 'cd /opt/jaot && \
  docker compose -f deploy/docker-compose.prod.yml run --rm migrate \
  alembic -c infra/alembic.ini downgrade 20260424c_phase74_byol_teardown'
```

This drops the `contact_messages` table. **Warning:** all submission history is lost —
including any rows in `pending` (Celery tasks will start logging "vanished" warnings) and
any rows the team has not yet replied to. Cold-storage backups (§6) can be used to restore
the table contents, but the operator must coordinate the restore manually.

Per the root `CLAUDE.md` "additive-only" rule, this rollback path exists but is reserved
for unrecoverable schema corruption only. Do NOT use it as a "let me try the migration
again" shortcut — the additive shape of `contact_messages` means a re-up has nothing to
roll back to in practice.

---

### Cross-references

- `monitoring/prometheus/alert_rules.yml` — alert rule definitions (group `contact_form`).
- `deploy/RUNBOOK-plausible.md` — precedent runbook (Phase 8).
- `deploy/RUNBOOK-disaster-recovery.md` — DB backup and restore procedures (cold storage).
- `app/api/v2/contact.py`, `app/tasks/contact_tasks.py`,
  `app/shared/core/prometheus_metrics.py` — source of truth for the producers of the
  counters referenced throughout this runbook.
