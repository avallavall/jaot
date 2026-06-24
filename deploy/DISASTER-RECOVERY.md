# JAOT Disaster Recovery Runbook

Domain: jaot.io
Deploy directory on the server: `/opt/jaot`
Compose file: `/opt/jaot/deploy/docker-compose.prod.yml`
SSH user: `jaot`
SSH key: `~/.ssh/id_ed25519_jaot` (override with `SSH_KEY` env var)

---

## Table of Contents

1. [Database Restore](#1-database-restore)
2. [Service Recovery](#2-service-recovery)
3. [Rollback](#3-rollback)
4. [Common Incidents](#4-common-incidents)
5. [Monitoring and Alerts](#5-monitoring-and-alerts)
6. [Solver License Management (Hexaly BYOL)](#6-solver-license-management-hexaly-byol)
7. [Backup Verification](#7-backup-verification)

---

## 1. Database Restore

All commands run on the server unless otherwise noted.

### 1.1 List Available Backups

```bash
/opt/jaot/deploy/restore.sh --list
```

This prints all backups organized by tier (daily, weekly, monthly) from `/opt/jaot/backups/`.

### 1.2 Restore from a Local Backup

```bash
/opt/jaot/deploy/restore.sh /opt/jaot/backups/daily/jaot_2026-03-25_0300.dump
```

The restore process:

1. Validates the backup file with `pg_restore --list`
2. Stops application services (api, celery_worker, celery_beat, frontend)
3. Runs `pg_restore -U jaot -d jaot --clean --if-exists` inside the `jaot_prod_postgres` container
4. Verifies the restore (table count, row count sanity check on `users` and `organizations`)
5. Restarts application services

**Note:** `pg_restore` may return a non-zero exit code for non-fatal warnings (e.g., "relation does not exist" during `--clean`). The script treats these as warnings, not failures.

### 1.3 Restore from Offsite

Requires `STORAGEBOX_USER` set in `/opt/jaot/.env.production`.

```bash
# Restore the most recent offsite backup
/opt/jaot/deploy/restore.sh --from-offsite

# Restore a backup from a specific date
/opt/jaot/deploy/restore.sh --from-offsite 2026-03-20
```

The script:
1. Fetches backups from the offsite storage host (configured via `STORAGEBOX_USER`) at `jaot-backups/daily/` via rsync over SSH port 23
2. Finds the most recent `.dump` file matching the date pattern
3. Proceeds with the standard restore process (stop services, pg_restore, verify, restart)
4. Cleans up the temporary download directory

### 1.4 Restore Encrypted Backups

If backups were encrypted with GPG (indicated by a `.gpg` extension), the restore script handles decryption automatically.

**Prerequisite:** The encryption key must exist at `/opt/jaot/.backup-key.gpg`.

```bash
# Works the same as a normal restore -- decryption is automatic
/opt/jaot/deploy/restore.sh /opt/jaot/backups/daily/jaot_2026-03-25_0300.dump.gpg
```

If the key is missing, the script exits with:
`Backup is encrypted but no key found at /opt/jaot/.backup-key.gpg`

**Recovery if key is lost:** Restore from an unencrypted backup (if available) or from the offsite backup target (backups are synced in whatever format they were created).

### 1.5 Verification After Restore

The restore script performs automatic verification:

- **Table count:** Queries `information_schema.tables` -- fails if zero tables found
- **Row count sanity check:** Counts rows in `users` and `organizations` tables

To manually verify:

```bash
# Check table count
docker exec jaot_prod_postgres psql -U jaot -d jaot -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"

# Check key tables
docker exec jaot_prod_postgres psql -U jaot -d jaot -c \
  "SELECT 'users' as tbl, count(*) FROM users UNION ALL SELECT 'organizations', count(*) FROM organizations;"

# Verify the API is responding
curl -s http://localhost:8001/api/v2/health/status
```

---

## 2. Service Recovery

### 2.1 Container Names

| Service | Container Name | Memory Limit |
|---------|---------------|-------------|
| PostgreSQL | `jaot_prod_postgres` | 1536 MB |
| Redis | `jaot_prod_redis` | 256 MB |
| RabbitMQ | `jaot_prod_rabbitmq` | 512 MB |
| Qdrant (RAG) | `jaot_prod_qdrant` | 384 MB |
| API (FastAPI) | `jaot_prod_api` | 4 GB |
| Celery Worker (default) | `jaot_prod_celery_default` | 256 MB |
| Celery Worker (SCIP) | `jaot_prod_celery_scip` | 3 GB |
| Celery Worker (HiGHS) | `jaot_prod_celery_highs` | 1 GB |
| Celery Worker (Hexaly) | `jaot_prod_celery_hexaly` | 2 GB |
| Celery Beat | `jaot_prod_beat` | 128 MB |
| Frontend (Next.js) | `jaot_prod_frontend` | 512 MB |
| Caddy (reverse proxy) | `jaot_prod_caddy` | 256 MB |
| Prometheus | `jaot_prod_prometheus` | 512 MB |
| Grafana | `jaot_prod_grafana` | 256 MB |
| Alertmanager | `jaot_prod_alertmanager` | 64 MB |
| Node Exporter | `jaot_prod_node_exporter` | 64 MB |
| cAdvisor | `jaot_prod_cadvisor` | 128 MB |
| Postgres Exporter | `jaot_prod_postgres_exporter` | 64 MB |
| Redis Exporter | `jaot_prod_redis_exporter` | 32 MB |
| Blackbox Exporter | `jaot_prod_blackbox` | 32 MB |
| Celery Exporter | `jaot_prod_celery_exporter` | 128 MB |

### 2.2 Restart an Individual Service

```bash
cd /opt/jaot

# Restart a single service without touching its dependencies
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps <service>

# Examples:
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps api
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps celery_worker
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps frontend
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps caddy
```

### 2.3 Restart the Entire Stack

```bash
cd /opt/jaot

# Graceful restart (recommended)
docker compose -f deploy/docker-compose.prod.yml down
docker compose -f deploy/docker-compose.prod.yml up -d

# Hard restart (if containers are stuck)
docker compose -f deploy/docker-compose.prod.yml kill
docker compose -f deploy/docker-compose.prod.yml up -d
```

### 2.4 Check Service Health

**From your local machine:**

```bash
./deploy/deploy.sh status
```

This SSHes into the server and checks the Docker health status of all core services.

**From the server:**

```bash
# All services at once
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml ps

# Specific container health
docker inspect --format='{{.State.Health.Status}}' jaot_prod_api
docker inspect --format='{{json .State.Health}}' jaot_prod_api
```

**Health check endpoints:**

| Service | Health Check |
|---------|-------------|
| API | `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/api/v2/health/status')"` |
| Celery Worker | `celery -A app.shared.core.celery_app inspect ping --timeout 5` |
| Celery Beat | PID file check: `kill -0 $(cat /tmp/celery-beat.pid)` |
| Frontend | `wget --spider -q http://127.0.0.1:3000/en` |
| Caddy | `wget --no-verbose --tries=1 --spider --header=Host:jaot.io http://localhost:80` |
| PostgreSQL | `pg_isready -U $POSTGRES_USER` |
| Redis | `REDISCLI_AUTH=$REDIS_PASSWORD redis-cli ping` |
| RabbitMQ | `rabbitmq-diagnostics -q ping` |
| Alertmanager | `wget --spider -q http://localhost:9093/-/healthy` |

### 2.5 Read Logs

```bash
cd /opt/jaot

# Follow logs for a specific service
docker compose -f deploy/docker-compose.prod.yml logs -f api
docker compose -f deploy/docker-compose.prod.yml logs -f celery_worker
docker compose -f deploy/docker-compose.prod.yml logs -f frontend
docker compose -f deploy/docker-compose.prod.yml logs -f postgres
docker compose -f deploy/docker-compose.prod.yml logs -f caddy

# Last 100 lines of a service
docker compose -f deploy/docker-compose.prod.yml logs --tail=100 api

# All services (combined)
docker compose -f deploy/docker-compose.prod.yml logs -f

# Direct Docker logs (with timestamps)
docker logs --since 30m jaot_prod_api
docker logs --since 1h --timestamps jaot_prod_celery
```

**Log configuration:** All containers use the `json-file` log driver with `max-size: 50m` and `max-file: 10` (500 MB max per service).

**Backup logs:**
- Backup log: `/opt/jaot/backups/backup.log`
- Restore log: `/opt/jaot/backups/restore.log`

---

## 3. Rollback

### 3.1 Rollback a Deploy

**From your local machine:**

```bash
./deploy/deploy.sh rollback
```

This command:

1. SSHes into the server
2. For each app service (api, celery_worker, celery_beat, frontend), restores the `:rollback` tagged image to `:latest`
3. Restarts all app services with `docker compose up -d --no-deps api celery_worker celery_beat frontend`
4. Waits for services to stabilize (health checks on api, celery, frontend)

**Important:** Rollback images are tagged automatically during `deploy.sh deploy` before new images are built. The rollback only restores the **previous** deploy's images.

### 3.2 Rollback to a Specific Version

There is no built-in command for multi-version rollback. The system only keeps one rollback tag (`:rollback` = the previous deploy).

**Manual approach:**

```bash
# On the server: list all image tags for a service
docker images --filter "reference=*jaot*" --format "{{.Repository}}:{{.Tag}} {{.CreatedAt}}"

# If the desired image exists locally, tag it and restart
docker tag <image-id> <repository>:latest
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml up -d --no-deps api
```

**If the image no longer exists locally:** You must rebuild from git.

```bash
# On the server
cd /opt/jaot
git checkout <commit-hash>
docker compose -f deploy/docker-compose.prod.yml build api
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps api
```

### 3.3 What to Do if Rollback Images Do Not Exist

This happens on the very first deploy or if Docker images have been pruned.

1. **Rebuild from the last known-good commit:**
   ```bash
   # From your local machine, deploy a specific commit
   git checkout <last-known-good-commit>
   ./deploy/deploy.sh deploy
   ```

2. **If the server has the git history:**
   ```bash
   # On the server
   cd /opt/jaot
   docker compose -f deploy/docker-compose.prod.yml build
   docker compose -f deploy/docker-compose.prod.yml up -d
   ```

3. **If you only need to fix the database:**
   ```bash
   /opt/jaot/deploy/restore.sh --list
   /opt/jaot/deploy/restore.sh /opt/jaot/backups/daily/<latest-good-backup>.dump
   ```

### 3.4 Database Rollback Warning

**Rollback does NOT revert database migrations.** Migrations are designed to be backward-compatible (additive-only). If a migration is destructive (DROP/RENAME), the only database recovery path is restoring from backup.

---

## 4. Common Incidents

### 4.1 Database Connection Exhaustion

**Alert:** `DbConnectionPoolExhausted` (critical, >90% of max connections) or `PostgresHighConnectionCount` (warning, >80%)

**Symptoms:** API returns 500 errors, new connections refused.

**PostgreSQL config:** `max_connections = 100` (from `deploy/config/postgresql.conf`)
**App pool:** `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=5` per service (api + celery_worker + celery_beat = up to 30 connections)

**Diagnosis:**

```bash
# Check current connections
docker exec jaot_prod_postgres psql -U jaot -d jaot -c \
  "SELECT state, count(*) FROM pg_stat_activity GROUP BY state ORDER BY count DESC;"

# Check connections by application
docker exec jaot_prod_postgres psql -U jaot -d jaot -c \
  "SELECT application_name, state, count(*) FROM pg_stat_activity GROUP BY 1, 2 ORDER BY 3 DESC;"

# Find long-running queries
docker exec jaot_prod_postgres psql -U jaot -d jaot -c \
  "SELECT pid, now() - pg_stat_activity.query_start AS duration, query, state
   FROM pg_stat_activity
   WHERE state != 'idle'
   ORDER BY duration DESC
   LIMIT 10;"
```

**Resolution:**

```bash
# 1. Kill idle connections older than 5 minutes
docker exec jaot_prod_postgres psql -U jaot -d jaot -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle' AND query_start < now() - interval '5 minutes';"

# 2. Restart the API and Celery to reset all connection pools
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml restart api celery_worker celery_beat
```

### 4.2 Redis Memory Full

**Alert:** `RedisHighMemoryUsage` (warning, >85% of max)

**Redis config:** `maxmemory 256mb`, `maxmemory-policy allkeys-lru` (from `deploy/config/redis.conf`)

**Diagnosis:**

```bash
# Check memory usage
docker exec jaot_prod_redis redis-cli -a "$REDIS_PASSWORD" INFO memory

# Check largest keys
docker exec jaot_prod_redis redis-cli -a "$REDIS_PASSWORD" --bigkeys
```

**Resolution:**

Redis is configured with `allkeys-lru` eviction, so it will automatically evict least-recently-used keys when memory is full. The data stored (rate limit counters, Celery result backends) is ephemeral.

```bash
# If you need to flush immediately (safe -- rate limits and cache will rebuild)
docker exec jaot_prod_redis redis-cli -a "$REDIS_PASSWORD" FLUSHALL

# Restart Redis
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml restart redis
```

### 4.3 RabbitMQ Queue Backlog

**Alerts:**
- `CeleryQueueBacklog` (warning, >100 messages ready for >10 minutes)
- `RabbitmqUnackedMessages` (warning, >50 unacked messages for >10 minutes)

**Diagnosis:**

```bash
# Check queue status via management API (bound to 127.0.0.1:15672)
docker exec jaot_prod_rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers

# Check if Celery workers are connected
docker exec jaot_prod_celery celery -A app.shared.core.celery_app inspect active
docker exec jaot_prod_celery celery -A app.shared.core.celery_app inspect reserved
```

**Resolution:**

```bash
# 1. Check if Celery worker is alive
docker inspect --format='{{.State.Health.Status}}' jaot_prod_celery

# 2. Restart Celery worker (processes queues: default, solve)
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml restart celery_worker

# 3. If queues are poisoned (stuck messages), purge them
docker exec jaot_prod_rabbitmq rabbitmqctl purge_queue default
docker exec jaot_prod_rabbitmq rabbitmqctl purge_queue solve

# 4. Restart Celery Beat (cron scheduler) if scheduled tasks are affected
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml restart celery_beat
```

### 4.4 Disk Space Full

**Alert:** `HighDiskUsage` (warning, <15% free)

**Diagnosis:**

```bash
# Check disk usage
df -h /

# Check Docker disk usage
docker system df
docker system df -v

# Check backup directory size
du -sh /opt/jaot/backups/*

# Check Docker log sizes
du -sh /var/lib/docker/containers/*/
```

**Resolution:**

```bash
# 1. Prune Docker resources (images, containers, build cache older than 7 days)
docker system prune -f --filter 'until=168h'

# 2. Prune dangling and unused images
docker image prune -a -f

# 3. Manually prune old backups (beyond normal retention)
ls -la /opt/jaot/backups/daily/
rm /opt/jaot/backups/daily/jaot_2026-03-01_0300.dump  # remove specific old backups

# 4. Clear Docker build cache
docker builder prune -f

# 5. Check and truncate large log files
truncate -s 0 /opt/jaot/backups/backup.log
```

### 4.5 TLS Certificate Issues

**Alert:** `TlsCertExpiringSoon` (warning, <7 days until expiry)

Caddy handles TLS certificates automatically via Let's Encrypt. Issues are typically caused by DNS misconfiguration or rate limiting.

**Diagnosis:**

```bash
# Check current certificate from outside
openssl s_client -connect jaot.io:443 -servername jaot.io </dev/null 2>/dev/null | openssl x509 -noout -dates

# Check Caddy logs for ACME errors
docker logs --since 1h jaot_prod_caddy | grep -i -E "acme|certificate|tls|error"

# Verify DNS resolves to the server IP
dig jaot.io A +short
```

**Resolution:**

```bash
# 1. Verify DNS points to the server
dig jaot.io A +short
# Should return the server IP

# 2. Restart Caddy (triggers certificate renewal)
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml restart caddy

# 3. If Caddy data volume is corrupted, reset it
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml stop caddy
docker volume rm jaot_caddy_data jaot_caddy_config
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml up -d caddy

# 4. Check that ports 80 and 443 are open
ufw status
# Should show 80/tcp ALLOW and 443/tcp ALLOW
```

### 4.6 OOM Kills

**Alert:** `ContainerOomKilled` (critical, immediate) or `ContainerHighMemoryUsage` (warning, >85% of limit)

**Diagnosis:**

```bash
# Check system-wide OOM events
dmesg | grep -i "oom\|killed process" | tail -20

# Check which containers were killed
docker ps -a --filter "status=exited" --format "{{.Names}} {{.Status}}"

# Check container memory usage
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"
```

**Resolution:**

```bash
# 1. Restart the killed container
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml up -d --no-deps <service>

# 2. Check if the problem is the SCIP solver (api or celery_worker, 4GB limit each)
docker logs --since 30m jaot_prod_celery | grep -i "memory\|oom\|killed"
docker logs --since 30m jaot_prod_api | grep -i "memory\|oom\|killed"

# 3. If OOM kills are recurring, check for memory leaks
docker stats --format "table {{.Name}}\t{{.MemUsage}}"
# Watch for steadily increasing memory over time
```

**Container memory limits for reference:**
- API: 4 GB (4 Uvicorn workers + SCIP solver)
- Celery Worker: 4 GB (SCIP solver on large MIP models can use 1-2 GB per solve)
- Frontend: 512 MB
- PostgreSQL: 1536 MB
- RabbitMQ: 512 MB
- Redis: 256 MB
- Celery Beat: 128 MB

---

## 5. Monitoring and Alerts

### 5.1 Where to Check Alerts

**Alertmanager** runs at `127.0.0.1:9093` on the server (not exposed publicly).

```bash
# SSH tunnel to access Alertmanager UI
ssh -L 9093:127.0.0.1:9093 -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP>
# Then open http://localhost:9093 in your browser
```

**Alert routing:** All alerts are sent via email to the address in `ALERT_EMAIL_RECIPIENT` (set in `.env.production`, substituted into the Alertmanager config at container start) through Resend SMTP (`smtp.resend.com:587`). Critical alerts repeat every 1 hour; warnings repeat every 4 hours.

**Alert inhibition rules:**
- If PostgreSQL is down, connection pool and deadlock alerts are suppressed
- If RabbitMQ is down, queue backlog and unacked message alerts are suppressed
- If Redis is down, Redis memory alerts are suppressed
- If a critical alert fires, the corresponding warning-severity alert is suppressed

### 5.2 How to Access Grafana

Grafana runs at `127.0.0.1:3001` on the server.

```bash
# SSH tunnel to access Grafana
ssh -L 3001:127.0.0.1:3001 -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP>
# Then open http://localhost:3001 in your browser
```

**Credentials:** Username is `jaot_admin` (or `GRAFANA_ADMIN_USER` from `.env.production`). Password is set via `GRAFANA_ADMIN_PASSWORD` in `.env.production`.

**Data sources:** Prometheus (auto-provisioned).

**Dashboards:** Auto-provisioned from `/opt/jaot/monitoring/grafana/dashboards/`.

### 5.3 How to Access Prometheus

```bash
# SSH tunnel
ssh -L 9090:127.0.0.1:9090 -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP>
# Then open http://localhost:9090 in your browser
```

Prometheus retains data for 15 days (`--storage.tsdb.retention.time=15d`).

### 5.4 How to Access RabbitMQ Management UI

```bash
# SSH tunnel
ssh -L 15672:127.0.0.1:15672 -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP>
# Then open http://localhost:15672 in your browser
```

Credentials: `RABBITMQ_USER` and `RABBITMQ_PASS` from `.env.production`.

### 5.5 Silence Alerts During Maintenance

**Via Alertmanager UI:**

1. Open SSH tunnel to `127.0.0.1:9093`
2. Go to http://localhost:9093/#/silences
3. Click "New Silence"
4. Set matchers (e.g., `alertname=~".*"` to silence all)
5. Set duration and comment

**Via command line:**

```bash
# Create a 2-hour silence for all alerts (replace <SERVER_IP>)
ssh -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP> \
  'curl -s -X POST http://localhost:9093/api/v2/silences -H "Content-Type: application/json" -d "{
    \"matchers\": [{\"name\": \"alertname\", \"value\": \".*\", \"isRegex\": true, \"isEqual\": true}],
    \"startsAt\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
    \"endsAt\": \"$(date -u -d '+2 hours' +%Y-%m-%dT%H:%M:%SZ)\",
    \"createdBy\": \"operator\",
    \"comment\": \"Planned maintenance\"
  }"'

# List active silences
ssh -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP> \
  'curl -s http://localhost:9093/api/v2/silences | jq ".[] | select(.status.state==\"active\") | {id, comment, endsAt}"'

# Delete a silence
ssh -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP> \
  'curl -s -X DELETE http://localhost:9093/api/v2/silence/<silence-id>'
```

### 5.6 Active Alert Rules

**41 alert rules across 13 groups** (see `monitoring/prometheus/alert_rules.yml`):

| Alert | Severity | Condition |
|-------|----------|-----------|
| **API** | | |
| HighApiErrorRate | critical | >10% of requests returning 5xx for 5m |
| HighApiLatencyP99 | warning | P99 latency >5s for 5m (excludes /solve) |
| ApiDown | critical | Prometheus cannot scrape API metrics for 1m |
| **Infrastructure** | | |
| ContainerOomKilled | critical | Any OOM kill on host (immediate) |
| HighDiskUsage | warning | <15% disk space free for 5m |
| HostHighMemoryUsage | warning | <10% available RAM for 5m |
| HostHighCpuUsage | warning | >85% CPU for 5m |
| **PostgreSQL** | | |
| DbConnectionPoolExhausted | critical | >90% of max_connections for 5m |
| PostgresDown | critical | Exporter cannot connect for 1m |
| PostgresHighConnectionCount | warning | >80% of max_connections for 5m |
| PostgresDeadlocks | warning | Deadlocks occurring for 5m |
| **RabbitMQ** | | |
| CeleryQueueBacklog | warning | >100 ready messages for 10m |
| RabbitmqDown | critical | Node not responding for 1m |
| RabbitmqHighMemoryUsage | warning | >85% of memory limit for 5m |
| RabbitmqUnackedMessages | warning | >50 unacked messages for 10m |
| **Redis** | | |
| RedisDown | critical | Redis unreachable for 1m |
| RedisHighMemoryUsage | warning | >85% of maxmemory for 5m |
| **Celery** | | |
| CeleryExporterDown | warning | Celery exporter unreachable |
| CeleryTaskFailureRateHigh | warning | >10% task failure rate |
| CeleryQueueDepthHigh | warning | >50 messages in any queue |
| **Containers** | | |
| TlsCertExpiringSoon | warning | Certificate expires within 7 days |
| CeleryWorkerDown | critical | Container not seen for 2m |
| ContainerHighMemoryUsage | warning | >85% of memory limit for 5m |
| ContainerRestarting | warning | >2 restarts in 15m |
| *(+ 16 more rules across jaot-hexaly-platform-license, jaot-qdrant, jaot-llm, jaot-security, contact_form, jaot-queue-routing groups)* | | |

### 5.7 Contact Information

- **Alert recipient:** the `ALERT_EMAIL_RECIPIENT` value in `.env.production`
- **Alert sender:** JAOT Alerts <noreply@jaot.io>
- **SMTP provider:** Resend (smtp.resend.com:587)
- **SMTP credential location:** `/opt/jaot/secrets/resend_api_key` (mounted into Alertmanager container)

---

## 6. Solver License Management (Hexaly BYOL)

Phase 7.4 (D-01) introduced an instance-level platform license model for Hexaly. The deploy operator mounts a single `.lic` file (BYOL) at `/etc/jaot/hexaly.lic` into the `celery_worker_hexaly` container. There is no per-organization license upload, no database table for licenses, and no encryption key rotation — the license is a plaintext file on the deploy host.

### 6.1 Hexaly Worker Recovery

The `celery_worker_hexaly` service runs a dedicated Docker image (`jaot-worker-hexaly`) that carries the `hexaly` SDK. The base `jaot-worker` image does NOT have the SDK — routing a Hexaly task to a base worker would fail with `Hexaly SDK is not installed on this worker`.

At container startup `HexalyAdapter.__init__` reads `/etc/jaot/hexaly.lic` and fails fast (RuntimeError → Docker healthcheck marks the container unhealthy) if the file is missing or already expired. Other workers (default/scip/highs) are unaffected.

**Verify the Hexaly worker is healthy:**

```bash
docker inspect --format='{{.State.Health.Status}}' jaot_prod_celery_hexaly
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml logs --tail=50 celery_worker_hexaly | grep -E "Q solve_hexaly|ready"
```

Expected log lines at worker startup:
```
Platform Hexaly license loaded: fingerprint=<8-hex> expires_at=...
[tasks] ... (hexaly@<hostname>) ready.
... Connected to amqp://...
... [queues] ... solve_hexaly exchange=solve_hexaly(direct) ...
```

**Restart only the Hexaly worker:**

```bash
cd /opt/jaot
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps celery_worker_hexaly
```

**Pull a new image after a CI build:**

```bash
cd /opt/jaot
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production pull celery_worker_hexaly
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production up -d --no-deps celery_worker_hexaly
```

**If the Hexaly image is missing from the registry:** build it from `deploy/docker/Dockerfile.worker.hexaly` (it extends the base worker image and installs `requirements-hexaly.txt`) and push it to your registry. Deployments without Hexaly can leave the service absent or scale to zero — no image publish, no pull failure, the rest of the stack is unaffected.

### 6.2 `hexaly` Wheel Source

The Hexaly worker image installs the pinned SDK from `requirements-hexaly.txt` (wheel served from `https://pip.hexaly.com`) — it is an optional extra, NOT part of `requirements.txt`. The index is public; the commercial gate is the runtime license (BYOL), not the SDK wheel itself. Pin bumps go through a dedicated plan — the HxSolutionStatus enum ordinals have changed between minor versions before, and our adapter's name-based fallback catches that but should not be relied on silently.

### 6.3 License Lifecycle (BYOL — instance level)

1. **Operator obtains a `.lic` file** from Hexaly support (one file per deployment instance).
2. **Place the file on the deploy host** at a path that will be bind-mounted into the container, e.g.:
   ```bash
   sudo cp hexaly.lic /etc/jaot/hexaly.lic
   sudo chown root:root /etc/jaot/hexaly.lic
   sudo chmod 600 /etc/jaot/hexaly.lic
   ```
3. **Ensure the volume mount is configured** in `deploy/docker-compose.prod.yml` under the `celery_worker_hexaly` service:
   ```yaml
   volumes:
     - /etc/jaot/hexaly.lic:/etc/jaot/hexaly.lic:ro
   ```
4. **Restart the Hexaly worker** so `HexalyAdapter.__init__` picks up the new file:
   ```bash
   cd /opt/jaot
   docker compose -f deploy/docker-compose.prod.yml --env-file .env.production up -d --no-deps celery_worker_hexaly
   ```
5. **Verify the worker is healthy** (see §6.1 above). The startup log should include `Platform Hexaly license loaded` with the file's sha256-prefix fingerprint and parsed `expires_at`.
6. **Per-solve activation:** `hexaly_license_scope()` injects the license plaintext into `HX_LICENSE_CONTENT` for the duration of the solve only, then clears it — defense-in-depth so a leaked exception cannot carry the license to the next task on the same worker process.
7. **Expiry monitoring:** the `hexaly_platform_license_expiry_sweep` Celery Beat task runs daily and updates the `HEXALY_LICENSE_DAYS_REMAINING` Prometheus gauge (Alertmanager alert group `jaot-hexaly-platform-license`). The gauge is set to `-1` (sentinel) when the file is missing or the expiry line cannot be parsed.

### 6.4 Replacing / Rotating the License

License rotation = swap the `.lic` file on the deploy host and restart the Hexaly worker. There is no encryption-key rotation.

**Procedure:**

1. **Place the new `.lic` on the deploy host:**
   ```bash
   sudo cp new-hexaly.lic /etc/jaot/hexaly.lic
   sudo chown root:root /etc/jaot/hexaly.lic
   sudo chmod 600 /etc/jaot/hexaly.lic
   ```

2. **Restart the Hexaly worker:**
   ```bash
   cd /opt/jaot
   docker compose -f deploy/docker-compose.prod.yml --env-file .env.production up -d --no-deps celery_worker_hexaly
   ```

3. **Confirm the worker picked up the new license** — the startup log must show the new fingerprint (sha256[:8] of the new `.lic`):
   ```bash
   docker logs jaot_prod_celery_worker_hexaly 2>&1 | grep "Platform Hexaly license loaded"
   ```

**Failure modes:**

- Worker exits immediately after restart: the new `.lic` is missing from the mount path, or has already expired. Check the path and file permissions, then verify the expiry date in the file.
- `RuntimeError: Platform Hexaly license expired`: the new `.lic` has a past `EXPIRES=` date. Obtain a renewed file from Hexaly support.

---

## 7. Backup Verification

### 7.1 Dry-Run Restore (Validate Without Restoring)

```bash
/opt/jaot/deploy/restore.sh --dry-run /opt/jaot/backups/daily/jaot_2026-03-25_0300.dump
```

This:
1. Checks the file exists and reports its size
2. Decrypts if needed (`.gpg` files)
3. Validates with `pg_restore --list` (reads the table of contents without restoring)
4. Prints the first 30 lines of the TOC
5. Does **not** stop services or modify the database

### 7.2 Verify Backup Integrity

```bash
# Validate that a backup file is readable by pg_restore
docker exec -i jaot_prod_postgres pg_restore --list < /opt/jaot/backups/daily/jaot_2026-03-25_0300.dump > /dev/null
echo $?  # 0 = valid, non-zero = corrupt

# Check file size (should be non-zero, typically several MB)
ls -lh /opt/jaot/backups/daily/

# If pg_restore is available on the host (outside Docker)
pg_restore --list /opt/jaot/backups/daily/jaot_2026-03-25_0300.dump > /dev/null
```

### 7.3 Backup Schedule and Retention

**Schedule:** Daily at 03:00 UTC (cron: `0 3 * * *`)

**Cron entry:**
```
0 3 * * * /opt/jaot/deploy/backup.sh >> /opt/jaot/backups/backup.log 2>&1
```

Install or reinstall the cron job:
```bash
/opt/jaot/deploy/backup.sh --install-cron
```

**Backup format:** `pg_dump` custom format (`-Fc`), compressed by default, supports parallel restore.

**Retention policy:**

| Tier | Location | Keep Count | Max Age | Promotion |
|------|----------|------------|---------|-----------|
| Daily | `/opt/jaot/backups/daily/` | 7 minimum | 7 days | Every backup |
| Weekly | `/opt/jaot/backups/weekly/` | 4 minimum | 28 days | Sundays |
| Monthly | `/opt/jaot/backups/monthly/` | 3 minimum | 90 days | 1st of month |

Backups are never deleted below the minimum keep count, even if they exceed the max age.

**Encryption:** If `/opt/jaot/.backup-key.gpg` exists, backups are encrypted with AES-256 (GPG symmetric). The unencrypted `.dump` file is deleted after encryption.

**Offsite sync:** If `STORAGEBOX_USER` is set in `.env.production`, backups are synced to the offsite storage target via rsync over SSH port 23 after each backup run.

**WAL archiving:** PostgreSQL is configured with `archive_mode = on`. WAL files are archived to `/var/lib/postgresql/wal_archive/` (Docker volume `jaot_wal_archive`). The backup script cleans up old WAL files after each successful backup.

### 7.4 Validate Backup System Health

```bash
# Dry-run validation (checks Docker, postgres container, backup dirs, msmtp, offsite config)
/opt/jaot/deploy/backup.sh --dry-run

# Test email notifications
/opt/jaot/deploy/backup.sh --notify-test

# Check backup log for recent runs
tail -50 /opt/jaot/backups/backup.log

# Verify cron is installed
crontab -l | grep backup
```

### 7.5 Manual Backup

```bash
# Run a full backup immediately (outside the cron schedule)
/opt/jaot/deploy/backup.sh

# The script uses flock to prevent concurrent runs -- if a backup is already
# running, the second invocation will exit with:
# "ERROR: Another backup is already running"
```

---

## Quick Reference: Emergency Commands

```bash
# SSH into the server
ssh -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP>

# Check all service health (from local machine)
./deploy/deploy.sh status

# Check all containers (from the server)
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml ps

# Restart everything (from the server)
cd /opt/jaot && docker compose -f deploy/docker-compose.prod.yml down && docker compose -f deploy/docker-compose.prod.yml up -d

# Rollback deploy (from local machine)
./deploy/deploy.sh rollback

# List backups (from the server)
/opt/jaot/deploy/restore.sh --list

# Restore latest daily backup (from the server)
/opt/jaot/deploy/restore.sh $(ls -1t /opt/jaot/backups/daily/*.dump* | head -1)

# Restore from offsite (from the server)
/opt/jaot/deploy/restore.sh --from-offsite

# View live logs (from the server)
docker compose -f /opt/jaot/deploy/docker-compose.prod.yml logs -f api celery_worker

# Open Grafana (from local machine, then visit http://localhost:3001)
ssh -L 3001:127.0.0.1:3001 -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP>

# Open Alertmanager (from local machine, then visit http://localhost:9093)
ssh -L 9093:127.0.0.1:9093 -i ~/.ssh/id_ed25519_jaot jaot@<SERVER_IP>

# Free disk space (from the server)
docker system prune -f --filter 'until=168h' && docker image prune -a -f
```
