# Hexaly Verification Runbook

> **STATUS: PRE-ACTIVATION CHECKLIST — NOT YET EXECUTED WITH A REAL LICENSE**
>
> This runbook has been written in advance of receiving a Hexaly `.lic` file.
> The Hexaly integration path is code-complete (Phase 7.4) and follows
> Hexaly's documented Python API and platform-license model, but it has
> **never been validated end-to-end with a real Hexaly license**. The steps
> below are the expected procedure and verification criteria to run on the
> first Hexaly-enabled deployment. Check off items as you execute them then.

**Scope:** Closes Phase 7 HUMAN-UAT items #1 (runtime `.lic` solve) and #5
(Celery beat 24h tick). Run this runbook on the first deploy of a
Hexaly-worker-enabled release (i.e. `jaot-worker-hexaly:<sha>` present in
`docker-compose.prod.yml`) where a real `.lic` file is available.

**Prerequisites:**

- Production (or staging) server with
  `docker-compose -f deploy/docker-compose.prod.yml` up
- A valid Hexaly `.lic` file mounted at `/etc/jaot/hexaly.lic` (see
  `DISASTER-RECOVERY.md §6.3`) — the container must report healthy before
  starting these checks
- `jaot-worker-hexaly` container healthy (see section 0)
- SSH access as user `jaot` to the server
- `kubectl`-free environment — we use `docker exec` and `docker logs` directly

---

## Table of Contents

0. [Preflight — Hexaly worker healthy](#0-preflight--hexaly-worker-healthy)
1. [Runtime Hexaly solve end-to-end with a real `.lic`](#1-runtime-hexaly-solve-end-to-end-with-a-real-lic)
2. [Celery Beat 24h tick — expiry notification + Prometheus](#2-celery-beat-24h-tick--expiry-notification--prometheus)
3. [Rollout checklist](#rollout-checklist)

---

## 0. Preflight — Hexaly worker healthy

1. SSH to the server:

   ```bash
   ssh -i ~/.ssh/id_ed25519_ci jaot@<SERVER_IP>
   cd /opt/jaot
   ```

2. Confirm the `.lic` file is mounted and readable by the container:

   ```bash
   docker exec jaot_prod_celery_worker_hexaly ls -la /etc/jaot/hexaly.lic
   ```

   **Expected:** file present, permissions `-r--------` or `-rw-------` (0400/0600).

3. Verify the worker startup log shows the license was loaded:

   ```bash
   docker logs jaot_prod_celery_worker_hexaly 2>&1 | grep "Platform Hexaly license loaded"
   ```

   **Expected:** one line with `fingerprint=<8-hex>` and `expires_at=<ISO date or "unknown">`.

4. Verify the Hexaly worker is running:

   ```bash
   docker compose -f deploy/docker-compose.prod.yml ps celery_worker_hexaly
   ```

   **Expected:** state = `running` (Up), health = `healthy`.

5. Check `/health/status`:

   ```bash
   curl -s https://jaot.io/api/v2/health/status | jq '.components[] | select(.name == "solver_worker_hexaly")'
   ```

   **Expected:**

   ```json
   {"name": "solver_worker_hexaly", "status": "healthy", "message": null}
   ```

   **If `status: degraded`:** inspect worker logs
   (`docker logs jaot_prod_celery_worker_hexaly`) for SDK import errors,
   missing `.lic` file, or queue mismatch.

---

## 1. Runtime Hexaly solve end-to-end with a real `.lic`

Closes **07-HUMAN-UAT.md item #1**.

The activation model is instance-level: the `.lic` is mounted at worker
startup (see `DISASTER-RECOVERY.md §6.3`). There is no per-organization
upload step — once the worker is healthy, any authenticated user in any org
can request a Hexaly solve.

### Steps

1. Submit a known-answer quadratic problem via async:

   ```bash
   curl -X POST https://jaot.io/api/v2/solve/async \
     -H "Authorization: Bearer $OWNER_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "solver_name": "hexaly",
       "variables": [
         {"name": "x", "type": "continuous", "lb": 0, "ub": 10},
         {"name": "y", "type": "continuous", "lb": 0, "ub": 10}
       ],
       "constraints": [
         {"expression": "x + y", "operator": "<=", "rhs": 10}
       ],
       "objective": {"expression": "x * y", "direction": "maximize"}
     }'
   ```

   **Expected:** HTTP 202 with `{"task_id": "tsk_...", "status": "queued"}`.

2. Poll the task to completion:

   ```bash
   TASK_ID=tsk_xxx  # from step 1
   curl -s "https://jaot.io/api/v2/solve/async/$TASK_ID" \
     -H "Authorization: Bearer $OWNER_API_KEY" | jq
   ```

   **Expected result on first activation** — after ≤60s (Hexaly time limit,
   configurable via `hexaly_default_time_limit_seconds` in PlatformSettings):

   ```json
   {
     "status": "OPTIMAL",
     "solver_used": "hexaly",
     "objective_value": 25.0,
     "variable_values": {"x": 5.0, "y": 5.0}
   }
   ```

   **Tolerance:** `objective_value` within ±1e-3 of 25.0; `x + y` within
   ±1e-4 of 10.

3. **Plaintext-license hygiene check** — this is the critical verification.
   Run each of the following commands; each MUST return zero matches.

   ```bash
   # 3a. Plaintext not in API logs
   docker logs jaot_prod_api 2>&1 | grep -c "HEXALY_LICENSE" || true
   docker logs jaot_prod_api 2>&1 | grep -c "BEGIN HEXALY" || true

   # 3b. Plaintext not in Hexaly worker logs
   docker logs jaot_prod_celery_worker_hexaly 2>&1 | grep -c "BEGIN HEXALY" || true

   # 3c. Plaintext not in Celery result backend (Redis)
   docker exec jaot_prod_redis redis-cli --scan --pattern 'celery-task-meta-*' \
     | xargs -I {} docker exec jaot_prod_redis redis-cli GET {} \
     | grep -c "BEGIN HEXALY" || true

   # 3d. Plaintext not in audit_logs
   docker exec jaot_prod_postgres psql -U jaot -d jaot -c \
     "SELECT COUNT(*) FROM audit_logs WHERE metadata::text LIKE '%BEGIN HEXALY%';"
   ```

   **Expected:** every command returns 0 (or the psql COUNT returns `0`).

   **If non-zero:** STOP — there is a plaintext-leak regression. Roll back the
   deploy and escalate to security review.

### Exit criteria (Item #1)

- [ ] Step 1 returns HTTP 202 with a valid task id
- [ ] Step 2 poll returns `status: OPTIMAL`, `objective_value ≈ 25.0`,
      `solver_used: "hexaly"`
- [ ] Step 3 all 4 plaintext-hygiene checks return 0
- [ ] Record Test #1 `result: [pass]` in the Hexaly UAT checklist

### Troubleshooting

- **Worker unhealthy at preflight:** the `.lic` file is missing from the
  mount path, or `HexalyAdapter.__init__` detected an expired license. Check
  `docker logs jaot_prod_celery_worker_hexaly` for the RuntimeError message.
  Fix the `.lic` file and restart the worker (see `DISASTER-RECOVERY.md §6.4`).
- **Task stays `queued` indefinitely:** the `solve_hexaly` queue binding is
  broken. Check `docker logs jaot_prod_celery_worker_hexaly` for
  `Ready. Celery connected to amqp://...` and
  `consumer: Connected ... Receiving` on the `solve_hexaly` queue.
- **Task fails with `hexaly_internal_error`:** the Hexaly SDK raised an
  exception during solve (logged server-side as `Hexaly solver error`). Check
  the worker logs for the full traceback.

---

## 2. Celery Beat 24h tick — expiry notification + Prometheus

Closes **07-HUMAN-UAT.md item #5**.

The `hexaly_platform_license_expiry_sweep` Celery Beat task reads the
instance-level `.lic` file directly (no database row) and updates the
`HEXALY_LICENSE_DAYS_REMAINING` Prometheus gauge.

### Steps

1. Place a `.lic` file whose `EXPIRES=` line is within the 7-day warning
   window (3 days out is convenient for testing), then restart the worker so
   `HexalyAdapter.__init__` loads it.

2. Trigger the beat task manually (don't wait 24h):

   ```bash
   docker exec jaot_prod_celery_beat celery -A app.shared.core.celery_app \
     call hexaly_platform_license_expiry_sweep
   ```

   **Expected:** the celery CLI returns a task id. Wait ~10s for the task to
   be consumed by the default worker.

3. Verify Prometheus gauge populated:

   ```bash
   curl -s http://localhost:9090/api/v1/query \
     --data-urlencode 'query=jaot_hexaly_platform_license_days_remaining' | jq
   ```

   **Expected on first activation:** at least one sample where `value` equals
   the days remaining until the expiry date in the `.lic` file. The label
   `license_fingerprint` should match the sha256[:8] logged at worker startup.

4. Verify alert rule fires (optional — requires 1h of sustained window):

   ```bash
   curl -s http://localhost:9090/api/v1/alerts | jq \
     '.data.alerts[] | select(.labels.alertname | startswith("HexalyPlatformLicense"))'
   ```

   **Expected (after ≥1h window when days ≤ 30):** alert present with
   `state: "firing"` from the `jaot-hexaly-platform-license` alert group.

### Exit criteria (Item #5)

- [ ] Step 3 Prometheus gauge `jaot_hexaly_platform_license_days_remaining` populated
      with the expected integer value and correct `license_fingerprint` label
- [ ] Step 4 alert fires within the window (if days ≤ 30)
- [ ] Record the verification result for this deployment

### Troubleshooting

- **Beat task never runs:** `docker logs jaot_prod_celery_beat` should show
  `hexaly_platform_license_expiry_sweep` in the `beat_schedule`. If missing,
  check `app/shared/core/celery_app.py::beat_schedule`.
- **Gauge is -1 (sentinel):** the `.lic` file is missing from the mount path
  OR the file does not contain a parseable `EXPIRES=`/`VALID_UNTIL=` line.
  The sentinel value is intentional — Alertmanager treats it as "unknown /
  possibly expired" and fires the warning.

---

## Rollout checklist

- [ ] Section 0 preflight green
- [ ] Section 1 Exit criteria all checked
- [ ] Section 2 Exit criteria all checked
- [ ] `07-HUMAN-UAT.md` frontmatter updated to `status: resolved`

## Version

- **Runbook version:** 2.0 (2026-06-25, Phase 7.4 / D-01 — rewritten for instance-level license model)
- **Next review:** on any change to `HexalyAdapter.__init__`,
  `hexaly_platform_license_expiry_sweep`, or `HEXALY_LIC_PATH`.
