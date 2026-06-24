# Plausible Self-Hosted Analytics — Operator Runbook

**Scope:** Brings up the self-hosted Plausible
Community Edition v3.2.0 instance on the JAOT production host so the product owner can read
anonymous visitor traffic for `jaot.io` from a dashboard accessed via SSH tunnel.
Source of truth for the executable contract (smoke probes): `deploy/scripts/smoke-plausible.sh`.

**Production target:** the server, IP `<SERVER_IP>` (update this section if the IP
changes — it is referenced by name throughout the document). SSH user: `jaot`. SSH key:
`~/.ssh/id_ed25519_ci`. Deploy directory on the server: `/opt/jaot`.

This runbook is intentionally command-first and terse. Two steps require physical human action
(DNS provisioning at the registrar and first-admin registration through the web UI) and are
called out explicitly — they cannot be automated by this runbook or by Claude.

---

## Table of Contents

1. [Prerequisites](#section-1--prerequisites)
2. [DNS provisioning (HUMAN ACTION)](#section-2--dns-provisioning-human-action)
3. [Secret generation](#section-3--secret-generation)
4. [First-time deploy](#section-4--first-time-deploy)
5. [First-admin bootstrap (HUMAN ACTION)](#section-5--first-admin-bootstrap-human-action)
6. [Add jaot.io as a site](#section-6--add-jaotio-as-a-site)
7. [Smoke verification](#section-7--smoke-verification)
8. [End-to-end success criterion (Phase 8 goal)](#section-8--end-to-end-success-criterion-phase-8-goal)
9. [Daily operation](#section-9--daily-operation)
   - 9.1 [Weekly adblock-loss observability](#section-91--weekly-adblock-loss-observability)
10. [Licensing note (AGPL vs MIT)](#section-10--licensing-note-agpl-vs-mit)
11. [Deferred items](#section-11--deferred-items)

---

## Section 1 — Prerequisites

| Prerequisite | Why | How to verify |
|---|---|---|
| Registrar access for `jaot.io` (ability to add DNS records) | Add the `plausible` CNAME so Caddy can provision Let's Encrypt | Log into the registrar control panel; confirm you can edit the `jaot.io` zone |
| SSH access to the server as user `jaot` | All commands run on the server unless explicitly noted as laptop-side | `ssh -i ~/.ssh/id_ed25519_ci jaot@<SERVER_IP> 'whoami'` returns `jaot` |
| `openssl` on the server | Generate `SECRET_KEY_BASE` and the dedicated Postgres password | `which openssl` returns `/usr/bin/openssl` |
| `docker compose` already in use on the server | All new services live in the existing `deploy/docker-compose.prod.yml` | `docker compose version` returns `Docker Compose version v2.x.x` |
| The 08-01 commits merged to `main` | The new compose services, ClickHouse XMLs, Caddy block, and `PlausibleScript` component must be present on disk | `cd /opt/jaot && git log --oneline -10 \| grep -c "feat(08-"` returns >= 3 |
| The latest images pulled | The compose triplet pins Plausible CE v3.2.0, ClickHouse 24.12-alpine, Postgres 16-alpine | `docker compose -f deploy/docker-compose.prod.yml --env-file .env.production pull plausible_db plausible_events_db plausible` exits 0 |

---

## Section 2 — DNS provisioning (HUMAN ACTION)

> **checkpoint: human-action** — no CLI exists for registrar mutation. This step MUST be
> completed before Section 4, because Caddy's Let's Encrypt ACME challenge requires the
> subdomain to resolve to the server IP BEFORE the first deploy attempt. **Reference Pitfall 5:**
> Let's Encrypt rate-limits failed certificate-issuance attempts to 5 per hour per domain;
> a botched first deploy on un-provisioned DNS will lock you out for an hour.

1. Log into the `jaot.io` DNS registrar control panel.
2. Add a new DNS record on the `jaot.io` zone:
   - **Type:** `CNAME`
   - **Name / Host:** `plausible`
   - **Value / Target:** `jaot.io`
   - **TTL:** registrar default (300s–3600s)
3. If the registrar does NOT propagate CNAMEs to the apex reliably (some registrars flatten
   apex `A` records but not CNAMEs that point at the apex), use an `A` record instead:
   - **Type:** `A`
   - **Name / Host:** `plausible`
   - **Value / Target:** `<SERVER_IP>`

### Verification

From the server (so we resolve against the server's recursive DNS, not the operator's laptop):

```bash
ssh -i ~/.ssh/id_ed25519_ci jaot@<SERVER_IP>
dig +short plausible.jaot.io
```

**Expected:** the output ends with `<SERVER_IP>` (either directly, if the `A` record path
was used, or after a `jaot.io.` CNAME chain). If the output is empty, DNS has not propagated
yet — wait 5 minutes and retry. If after 30 minutes it is still empty, recheck the registrar
TTL and confirm no wildcard `A` record is overriding the new entry.

---

## Section 3 — Secret generation

Two new secrets must be set in `.env.production` BEFORE the first deploy:
`PLAUSIBLE_SECRET_KEY_BASE` (Plausible's session-cookie signing key) and
`PLAUSIBLE_POSTGRES_PASSWORD` (the password for the dedicated `plausible_db` Postgres user).

**Reference Pitfall 2:** Plausible requires `SECRET_KEY_BASE` to be AT LEAST 64 characters.
`openssl rand -base64 48` produces 64 base64 characters. Anything shorter causes the
Plausible container to crash-loop on startup with a confusing `SECRET_KEY_BASE` error.

### Steps

1. SSH to the server:

   ```bash
   ssh -i ~/.ssh/id_ed25519_ci jaot@<SERVER_IP>
   cd /opt/jaot
   ```

2. Generate `SECRET_KEY_BASE` and capture it to a file under `deploy/secrets/` (also printed
   to stdout for paste into `.env.production`):

   ```bash
   openssl rand -base64 48 | tee deploy/secrets/plausible_secret_key_base
   ```

3. Lock down the file:

   ```bash
   chmod 600 deploy/secrets/plausible_secret_key_base
   chown jaot:jaot deploy/secrets/plausible_secret_key_base
   ```

4. Generate a strong password for the dedicated Postgres:

   ```bash
   openssl rand -base64 24
   ```

   Copy the output (it will not be saved to disk in this step — it is pasted directly into
   `.env.production` in the next step).

5. Edit `.env.production` with vim and set both variables:

   ```bash
   vim .env.production
   ```

   Set (paste the actual values from steps 2 and 4 — do NOT commit them anywhere):

   ```
   PLAUSIBLE_SECRET_KEY_BASE=<paste the openssl rand -base64 48 output here>
   PLAUSIBLE_POSTGRES_PASSWORD=<paste the openssl rand -base64 24 output here>
   ```

6. Verify the env file parses correctly and contains both new keys:

   ```bash
   bash deploy/validate-env.sh
   ```

   **Expected:** no errors flagging `PLAUSIBLE_SECRET_KEY_BASE` or `PLAUSIBLE_POSTGRES_PASSWORD`
   as missing. (If `deploy/validate-env.sh` does not yet check the two new keys, that script
   is out of scope for this phase — visually confirm both lines are present in
   `.env.production` with `grep -c '^PLAUSIBLE_' .env.production` returning 2.)

---

## Section 4 — First-time deploy

1. From the server, in `/opt/jaot`, bring up the three new services:

   ```bash
   cd /opt/jaot
   docker compose -f deploy/docker-compose.prod.yml --env-file .env.production up -d plausible_db plausible_events_db plausible
   ```

2. Wait up to 2 minutes for all three to reach `Up (healthy)`. **Reference Pitfall 6:** the
   `plausible` service healthcheck has `start_period: 90s` because the entrypoint runs
   `db createdb && db migrate && run` before the HTTP listener opens. Premature healthcheck
   panic is normal during this window.

   ```bash
   docker compose -f deploy/docker-compose.prod.yml ps plausible_db plausible_events_db plausible
   ```

   **Expected after ~90 seconds:** all three rows show `Up (healthy)`.

3. Reload Caddy so the new `plausible.jaot.io` site block takes effect:

   ```bash
   docker compose -f deploy/docker-compose.prod.yml exec caddy caddy reload --config /etc/caddy/Caddyfile
   ```

4. Watch the Caddy logs for the Let's Encrypt cert issuance — expect a successful certificate
   line within 1 minute of the reload (assuming DNS from Section 2 is propagated):

   ```bash
   docker compose -f deploy/docker-compose.prod.yml logs -f caddy | grep plausible.jaot.io
   ```

   **Expected:** a line containing `certificate obtained successfully` for
   `plausible.jaot.io`. If you see `failed to obtain certificate`, re-verify DNS and check
   the rate-limit window (Pitfall 5) before retrying.

5. Stop tailing the logs (Ctrl-C). Plausible is now up and reachable internally on the
   Docker network as `plausible:8000`, and externally as `https://plausible.jaot.io` for
   the two allow-listed endpoints (`/js/script.js` and `/api/event`).

---

## Section 5 — First-admin bootstrap (HUMAN ACTION)

> **checkpoint: human-action** — Plausible v3 has NO `init-admin` CLI. The first registration
> is always allowed regardless of `DISABLE_REGISTRATION=true`. After the first user is
> created, subsequent attempts to access `/register` return "registration disabled."

**Reference Pitfall 1:** operators who do not know about the v3 one-shot exception file
false "I'm locked out" tickets. Read this section before opening the tunnel.

### Steps (from the operator's laptop, NOT from the server)

1. Open an SSH tunnel from the laptop to the server, forwarding local port 8000 to the
   `plausible` container's port 8000 inside the Docker network. This mirrors the existing
   Grafana access pattern on port 3001:

   ```bash
   ssh -i ~/.ssh/id_ed25519_ci -L 8000:plausible:8000 jaot@<SERVER_IP>
   ```

   Leave this terminal open for the duration of the bootstrap.

2. In a browser on the laptop, open:

   ```
   http://localhost:8000/register
   ```

3. Fill in the registration form with the admin account details:
   - **Email:** a real address you (or the operator team) controls
   - **Name:** `JAOT Plausible Admin` (or similar)
   - **Password:** generate from a password manager — minimum 12 characters, mixed case,
     numbers, symbols

4. Submit. You will be redirected to the dashboard. **Confirm the one-shot exception
   activated:** open a second browser tab (or incognito window) and visit
   `http://localhost:8000/register` again. It should redirect to `/login` or display
   "registration disabled."

### Sub-step 5b — Persist credentials to `deploy/secrets/` (CONTEXT D-08 requirement)

After the one-shot registration succeeds, the operator MUST mirror the credentials into the
shared on-host secrets store for handover continuity. The next operator who takes over from
a different machine cannot reach a personal password manager that lives on the original
operator's device — the file under `deploy/secrets/` is the authoritative on-host source of
truth.

> **Important — gitignore safety check FIRST.** Before writing the credentials file, confirm
> it will not be accidentally committed. Run on the server:
>
> ```bash
> cd /opt/jaot
> grep -E '^deploy/secrets/plausible_admin' .gitignore || \
>   echo 'deploy/secrets/plausible_admin.txt' >> .gitignore
> git check-ignore -v deploy/secrets/plausible_admin.txt
> ```
>
> The `git check-ignore` command MUST print a `.gitignore` rule that matches the file. If it
> exits non-zero (no rule matched), do NOT proceed — first ensure the line was added to
> `.gitignore` (the heredoc above does this), then re-run `git check-ignore -v`.

Once gitignore protection is confirmed, persist the credentials. On the server (`jaot@<SERVER_IP>`),
in `/opt/jaot`:

```bash
# Write the two-line credentials file (line 1 = email, line 2 = password):
cat > deploy/secrets/plausible_admin.txt <<EOF
<EMAIL>
<PASSWORD>
EOF
chmod 600 deploy/secrets/plausible_admin.txt
chown jaot:jaot deploy/secrets/plausible_admin.txt
```

Replace `<EMAIL>` and `<PASSWORD>` with the credentials just registered in step 3.

**Why this matters (CONTEXT D-08 rationale):** D-08 explicitly states that Plausible admin
credentials live in `deploy/secrets/`. A personal password manager entry is NOT a substitute
for the on-host file — the next operator taking over from a different machine cannot reach
a personal vault. The file is the authoritative source of truth for operator handover and
continuity scenarios; the current operator MAY also copy the credentials to a personal vault
for redundancy, but the on-host file is mandatory. The `chmod 600` + `chown jaot:jaot`
combination enforces host-level isolation that mirrors the existing `deploy/secrets/`
permissions pattern (compare `deploy/secrets/hexaly.lic.example` permissions).

### Verification

```bash
ls -l /opt/jaot/deploy/secrets/plausible_admin.txt
# Expected (single line): -rw------- 1 jaot jaot <size> <date> /opt/jaot/deploy/secrets/plausible_admin.txt
stat -c '%a %U:%G' /opt/jaot/deploy/secrets/plausible_admin.txt
# Expected: 600 jaot:jaot
```

---

## Section 6 — Add jaot.io as a site

With the SSH tunnel from Section 5 still open and the browser logged in as the admin account:

1. Navigate to `Sites` → `Add a website`.
2. **Domain:** enter `jaot.io` (NOT `plausible.jaot.io` — the tracker reports the SOURCE
   site, not the analytics host).
3. **Reporting timezone:** pick the timezone the operator uses for dashboard reading
   (e.g., `Europe/Madrid`).
4. Click `Add Site`.

You will be shown a JavaScript snippet to install. **Skip this step** — JAOT already ships
`<PlausibleScript />` via the `(public)/layout.tsx` (Wave 1 Task 3). The snippet display is
informational only.

---

## Section 7 — Smoke verification

From the operator's laptop (NOT the server — the smoke script verifies the PUBLIC endpoint
surface as seen by an arbitrary internet client):

```bash
cd /path/to/jaot/checkout
bash deploy/scripts/smoke-plausible.sh
```

**Expected:** exit 0 with all 6 probes PASS:

```
  [PASS] HTTPS https://plausible.jaot.io/js/script.js responds (200, application/javascript)
  [PASS] /login returns 404
  [PASS] /register returns 404
  [PASS] /api/v2/query returns 404
  [PASS] / returns 404
  [PASS] POST /api/event returns 202
```

### Troubleshooting

If any probe FAILS:

- **Probe 1 (script.js) FAILS with 000 or timeout:** DNS not yet propagated. Re-run Section
  2 verification. Wait 10 minutes if the registrar TTL is high.
- **Probe 1 FAILS with SSL/TLS error:** Caddy did not issue the LE certificate. Check Caddy
  logs (`docker compose ... logs caddy | grep plausible.jaot.io`). If you see ACME rate-limit
  hits, wait 1 hour (Pitfall 5).
- **Probes 2-5 (404 expected) return non-404:** the Caddy site block is not loading the
  allow-list default. Re-run `caddy reload` from Section 4 step 3.
- **Probe 6 (POST /api/event) returns 502:** Plausible app is up but Caddy cannot reach
  `plausible:8000`. Verify the `plausible` service is on BOTH `plausible_backend` AND
  `frontend` networks (the Caddy reverse_proxy reaches `plausible` via the SHARED `frontend`
  network — `backend` membership would NOT work because Caddy is not on `backend`; this is
  the B-1 REGRESSION GATE from 08-01 Task 1).
- **Probe 6 returns 502 with `plausible` reportedly healthy:** the container may be still
  booting through `db createdb && db migrate`. Wait 90 seconds and re-run (Pitfall 6).
- **`plausible_events_db` exits immediately on container start:** Pitfall 3 (CPU SIMD
  support). Verify on the server: `cat /proc/cpuinfo | grep sse4_2` returns at least one line.

---

## Section 8 — End-to-end success criterion (Phase 8 goal)

This is the test that confirms the Phase 8 user story is provably satisfied. The user story:
"As a JAOT product owner, I want to see anonymous visitor traffic
on jaot.io in a self-hosted dashboard, so that I can know if there is real traffic reaching
jaot.io."

1. On a personal device (laptop or phone) that is NOT on the same network as any active SSH
   tunnel, and with NO adblocker active (open an incognito/private window — most adblock
   extensions also load there, so confirm the personal device's network is clean too; refer
   to Pitfall 7), visit:

   ```
   https://jaot.io/pricing
   ```

2. Wait up to 60 seconds.

3. From the operator's laptop, re-open the SSH-tunneled dashboard:

   ```bash
   ssh -i ~/.ssh/id_ed25519_ci -L 8000:plausible:8000 jaot@<SERVER_IP>
   ```

   In a browser: `http://localhost:8000`. Click on the `jaot.io` site.

4. **Expected:** the dashboard shows a pageview count of at least 1 for `/pricing` within
   the last 5 minutes. The "Current visitors" widget may also show 1 if the visit was very
   recent.

If the count remains at 0 after 60 seconds:

- Confirm the visit reached the public site (open the network tab in the personal device's
  browser; look for a successful `POST` to `https://plausible.jaot.io/api/event`).
- If no such request appears, the personal device IS running an adblocker. Try a different
  network or a different browser.
- If the request appears but the dashboard does not update, Plausible may be filtering the
  request as a bot. Open `Top Sources` → `All Traffic` and check the User-Agent panel.

---

## Section 9 — Daily operation

### Dashboard access

The Plausible dashboard is not exposed on the public internet. The operator accesses it via
the same SSH-tunnel pattern used for Grafana on port 3001. The `plausible` service publishes
its port to `127.0.0.1:8800` on the server host (NOT `0.0.0.0` — internet-unreachable;
host-port 8800 because another local service already binds `127.0.0.1:8000`). Open the tunnel:

```bash
ssh -i ~/.ssh/id_ed25519_ci -L 8000:127.0.0.1:8800 jaot@<SERVER_IP>
```

If your local SSH config (`~/.ssh/config`) has the key set as the default identity for
`<SERVER_IP>`, the shorter form works too:

```bash
ssh -L 8000:127.0.0.1:8800 jaot@<SERVER_IP>
```

Then in a browser on the laptop: `http://localhost:8000`. Login with the credentials from
`deploy/secrets/plausible_admin.txt`.

> **Historical note:** an earlier draft of this runbook said
> `ssh -L 8000:plausible:8000 jaot@<SERVER_IP>`. That command fails silently because the
> `plausible` hostname only exists inside the Docker networks (`frontend` + `plausible_backend`)
> and is not resolvable from the server host. The IP-based form `ssh -L 8000:172.20.0.4:8000` works
> but is volatile (Docker re-assigns IPs on container recreate). The current `127.0.0.1:8800`
> form is stable across recreates and was added to the compose in the same operator-checkpoint
> session that finalised Phase 8.

### Backups

The two stateful Plausible volumes — `jaot_plausible_db_data` (Postgres) and
`jaot_plausible_event_data` (ClickHouse) — were tagged with `com.jaot.backup: "daily"` in
the 08-01 compose changes. The existing `deploy/backup.sh` is currently scoped to
`jaot_prod_postgres` only and does NOT yet dump ClickHouse or the Plausible-Postgres. Until a
follow-up plan extends `deploy/backup.sh`, the only retention story for Plausible data is
the underlying Docker volume snapshots maintained at the host level.

This is acceptable for the MVP phase because: (a) Plausible event data is rebuildable from
nothing in the sense that future traffic re-populates the dashboard, (b) the loss tolerance
for analytics history is materially higher than for transactional JAOT data.

### Section 9.1 — Weekly adblock-loss observability

At each weekly ops review, compare server-side public-page hits (Caddy access log) against
Plausible dashboard pageview counts for the same window. This is the W-4 absorption — the
T-08-01-09 adblock-loss threat is made operationally tractable by a concrete computed
threshold.

```bash
# On the server, count public-page hits over the last 7 days from the Caddy access log:
grep -cE 'GET / (HTTP|"|$)|GET /pricing|GET /marketplace|GET /docs' /var/log/caddy/access.log
# Then open the Plausible dashboard via SSH tunnel and read the pageview count for the same 7-day window.
```

**Expected ratio:** Plausible count >= ~70% of Caddy hits (allowing for adblockers, Plausible's
own bot filtering, and crawler exclusion).

**Trigger threshold:** if the delta exceeds 30% (Plausible < 70% of Caddy), promote the
deferred "anti-adblocker proxying through main domain" item from Section 11 to a planned
phase. This makes T-08-01-09 a computable, operationally tractable threat rather than a
static assertion.

---

## Section 10 — Licensing note (AGPL vs MIT)

**Reference Pitfall 8:** legal review or audit may flag "Plausible is AGPL" as a concern.
The answer is in this section so the review can resolve in 30 seconds.

> The Plausible APPLICATION container (`ghcr.io/plausible/community-edition:v3.2.0`) is
> AGPL v3-licensed. JAOT runs the OFFICIAL upstream container UNMODIFIED, so AGPL's source-
> disclosure obligation does NOT trigger — AGPL requires source disclosure only when the
> licensed software is MODIFIED. Pulling and running the published image is not a
> modification.
>
> The embedded JavaScript tracker (`script.js`, served from `https://plausible.jaot.io/js/script.js`)
> is MIT-licensed by design. Plausible explicitly split the licenses — application AGPL,
> tracker MIT — precisely to prevent AGPL virality on embedding sites. The fact that
> `jaot.io`'s frontend loads `script.js` creates NO AGPL obligation on the JAOT codebase.
>
> Reference: <https://plausible.io/blog/open-source-licenses>

---

## Section 11 — Deferred items

The following items were explicitly scoped OUT of Phase 8 and remain DEFERRED. They are
enumerated here so they do not become silent tech debt. Each has a trigger that determines
when it should be reconsidered.

- **Custom event tracking** (signup, pricing-to-signup CTA click, marketplace model purchase
  events). Deferred to a future "Conversion funnel telemetry" phase. **Revisit trigger:**
  product asks for funnel metrics or A/B test instrumentation.
- **Tracking logged-in surfaces** (`/workspace/*`, `/builder/*`, `/solve/*`, `/admin/*`,
  `/billing/*`, `/triggers/*`). Requires privacy review and per-user opt-in. **Revisit
  trigger:** product asks for usage analytics on authenticated workflows.
- **Anti-adblocker script proxying** through `jaot.io/js/script.js` instead of the dedicated
  subdomain. Phase 8 accepts ~30% adblock loss. **Revisit trigger:** Section 9.1 weekly
  comparison shows Plausible count < 70% of Caddy public-page hits.
- **Cookie banner cleanup** — remove the unused `analytics` toggle in
  `frontend/src/components/legal/CookieConsent.tsx` and the `analytics` field in
  `frontend/src/lib/cookie-consent.ts`. Plausible is cookieless by design (D-07) so the
  toggle is decorative. Standalone chore commit — can land at any time. **Revisit trigger:**
  any UX review of the cookie banner.
- **Plausible metrics scraped by Prometheus + Grafana dashboard.** Useful operationally
  (Plausible up/down, ClickHouse query latency) but not part of the MVP "see traffic" goal.
  **Revisit trigger:** ops asks for unified observability across all services.

---

**Last updated:** 2026-05-15 — Phase 8 initial publication.
