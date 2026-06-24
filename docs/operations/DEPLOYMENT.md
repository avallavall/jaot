# Deployment Guide — JAOT v2

**Target:** a self-hosted Linux server
**Reverse proxy:** Caddy (automatic TLS via Let's Encrypt)
**Domain:** jaot.io

---

## Services

Production runs **24 containers** (plus 1 one-shot `migrate`) across four Docker networks (`frontend`, `backend`, `monitoring`, `plausible_backend`). The Hexaly worker (`celery_worker_hexaly`) is profile-gated and only runs on deployments with a Hexaly platform license.

### Application

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| `postgres` | jaot_prod_postgres | 5432 (internal) | PostgreSQL 18 — primary database |
| `redis` | jaot_prod_redis | 6379 (internal) | Cache and rate limiting |
| `rabbitmq` | jaot_prod_rabbitmq | 15672 (localhost) | Message broker (management UI on 15672) |
| `qdrant` | jaot_prod_qdrant | 6333 (internal) | Qdrant vector DB for RAG (384-dim, 186 docs indexed) |
| `api` | jaot_prod_api | 8001 (internal) | FastAPI backend, 4 Uvicorn workers |
| `celery_worker_default` | jaot_prod_celery_default | -- | Default queue (`jaot_default`): email, webhooks, cron (256 MB) |
| `celery_worker_scip` | jaot_prod_celery_scip | -- | SCIP solver queue (`solve_scip`) — 3 GB |
| `celery_worker_highs` | jaot_prod_celery_highs | -- | HiGHS solver queue (`solve_highs`) — 1 GB |
| `celery_worker_hexaly` | jaot_prod_celery_hexaly | -- | Hexaly solver queue (`solve_hexaly`) — 2 GB; profile: hexaly |
| `celery_beat` | jaot_prod_beat | -- | Cron scheduler (DB-backed via sqlalchemy_celery_beat) |
| `frontend` | jaot_prod_frontend | 3000 (internal) | Next.js 16 (production build) |
| `caddy` | jaot_prod_caddy | 80, 443 | Reverse proxy with automatic TLS |
| `migrate` | jaot_prod_migrate | -- | One-shot Alembic migration runner (profile: migrate) |

### Plausible Analytics

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| `plausible_db` | jaot_prod_plausible_db | internal | Plausible postgres 16 (plausible_backend network) |
| `plausible_events_db` | jaot_prod_plausible_clickhouse | internal | ClickHouse 24.12 (plausible_backend network) |
| `plausible` | jaot_prod_plausible | 8800→8000 (localhost) | Plausible CE v3.2.0; dashboard via SSH tunnel |

### Monitoring

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| `prometheus` | jaot_prod_prometheus | 9090 (localhost) | Metrics collection, 15s scrape interval, 15d retention |
| `grafana` | jaot_prod_grafana | 3001 (localhost) | Dashboards and visualization |
| `alertmanager` | jaot_prod_alertmanager | 9093 (internal) | Alert routing and email notification via Resend |
| `node-exporter` | jaot_prod_node_exporter | 9100 (internal) | Host CPU, memory, disk, network metrics |
| `cadvisor` | jaot_prod_cadvisor | 8080 (internal) | Per-container resource metrics |
| `postgres-exporter` | jaot_prod_postgres_exporter | 9187 (internal) | PostgreSQL connection pool, deadlocks, replication |
| `redis-exporter` | jaot_prod_redis_exporter | 9121 (internal) | Redis memory, connected clients, hit rate |
| `celery-exporter` | jaot_prod_celery_exporter | 9808 (internal) | Celery task throughput, failure rate, queue depth |
| `blackbox-exporter` | jaot_prod_blackbox | 9115 (internal) | TLS certificate expiry probing for jaot.io:443 |

---

## Quick Start (Production)

### 1. Prepare environment

```bash
cd deploy
cp .env.production.example ../.env.production
```

Edit `.env.production` and set all `[REQUIRED]` values. Place the Resend API key in:

```bash
mkdir -p ../secrets
echo "re_YOUR_KEY_HERE" > ../secrets/resend_api_key
chmod 600 ../secrets/resend_api_key
```

### 2. Run database migrations

```bash
docker compose -f deploy/docker-compose.prod.yml --profile migrate run --rm migrate
```

### 3. Start all services

```bash
docker compose -f deploy/docker-compose.prod.yml up -d
```

### 4. Verify

```bash
# Health check
curl -s https://jaot.io/api/v2/health/status | jq .

# Container status
docker compose -f deploy/docker-compose.prod.yml ps

# Grafana (SSH tunnel or localhost)
open http://localhost:3001

# Prometheus (SSH tunnel or localhost)
open http://localhost:9090
```

---

## Configuration

JAOT uses a two-tier configuration architecture:

### Tier 1 — `.env.production` (infrastructure)

Loaded at container startup, before the database is available. Contains only infrastructure variables.

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `REDIS_PASSWORD` | Yes | Redis password |
| `RABBITMQ_PASS` | Yes | RabbitMQ password |
| `JWT_SECRET` | Yes | Min 32 chars: `openssl rand -hex 32` |
| `GRAFANA_ADMIN_PASSWORD` | Yes | Grafana admin password |
| `ALERT_EMAIL_RECIPIENT` | Yes | Alert destination (e.g. ops@jaot.io) |
| `POSTGRES_USER` | No | Default: `jaot` |
| `POSTGRES_DB` | No | Default: `jaot` |
| `RABBITMQ_USER` | No | Default: `jaot` |
| `GRAFANA_ADMIN_USER` | No | Default: `jaot_admin` |
| `DB_POOL_SIZE` | No | Default: `5` |
| `DB_MAX_OVERFLOW` | No | Default: `5` |
| `WORKERS` | No | Uvicorn workers, default: `4` |

See `deploy/.env.production.example` for the full list.

### Tier 2 — `platform_settings` DB table (business config)

All business configuration (plans, pricing, LLM keys, Stripe, SMTP, feature flags, rate limits, storage, etc.) is stored in the `platform_settings` database table and managed via the admin panel at runtime. The source of truth for defaults is `app/services/settings_registry.py` (84 entries).

Access business config at runtime through `PlatformSettingsService` (PSS), not `settings.*` or environment variables.

### Secrets

| Secret | Mount path | Used by |
|--------|-----------|---------|
| Resend API key | `secrets/resend_api_key` | Alertmanager (SMTP auth for email alerts) |

---

## Monitoring

### Architecture

```
Prometheus (scrape 15s) ──→ Alert Rules (24 rules, 7 groups)
    │                              │
    ├── node-exporter              ├──→ Alertmanager ──→ Email (Resend SMTP)
    ├── cadvisor                   │
    ├── postgres-exporter          └──→ Grafana dashboards
    ├── redis-exporter
    ├── celery-exporter
    ├── blackbox-exporter
    └── jaot-api (/metrics)
```

Prometheus scrapes 8 targets every 15 seconds and evaluates alert rules at the same interval. Data is retained for 15 days. Alertmanager routes alerts to email via Resend SMTP. Grafana auto-provisions a Prometheus datasource and the JAOT Overview dashboard on first boot.

### Access

| UI | URL | Auth |
|----|-----|------|
| Grafana | `http://localhost:3001` | `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` |
| Prometheus | `http://localhost:9090` | None (localhost-only binding) |
| RabbitMQ | `http://localhost:15672` | `RABBITMQ_USER` / `RABBITMQ_PASS` |

All monitoring ports are bound to `127.0.0.1` and are not exposed externally. Access them via SSH tunnel:

```bash
ssh -i ~/.ssh/<your-key> -L 3001:127.0.0.1:3001 -L 9090:127.0.0.1:9090 <user>@<your-server>
```

### Dashboard

The **JAOT Overview** dashboard is auto-provisioned from `monitoring/grafana/dashboards/jaot-overview.json`. It is loaded on startup and refreshed every 30 seconds. No manual import is required.

### Alert Rules

41 rules organized into 13 groups. The core operational groups:

| Group | Rules | Key alerts |
|-------|-------|------------|
| `jaot-api` | 3 | HighApiErrorRate (>10% 5xx), HighApiLatencyP99 (>5s), ApiDown |
| `jaot-infrastructure` | 4 | ContainerOomKilled, HighDiskUsage (>85%), HostHighMemoryUsage (>90%), HostHighCpuUsage (>85%) |
| `jaot-postgres` | 4 | PostgresDown, DbConnectionPoolExhausted (>90%), PostgresHighConnectionCount (>80%), PostgresDeadlocks |
| `jaot-rabbitmq` | 4 | RabbitmqDown, CeleryQueueBacklog (>100 msgs), RabbitmqHighMemoryUsage (>85%), RabbitmqUnackedMessages (>50) |
| `jaot-redis` | 2 | RedisDown, RedisHighMemoryUsage (>85%) |
| `jaot-celery` | 3 | CeleryExporterDown, CeleryTaskFailureRateHigh (>10%), CeleryQueueDepthHigh (>50) |
| `jaot-containers` | 4 | TlsCertExpiringSoon (<7d), CeleryWorkerDown, ContainerHighMemoryUsage (>85%), ContainerRestarting (>2 in 15m) |

Plus `jaot-hexaly-platform-license`, `jaot-qdrant`, `jaot-llm`, `jaot-security`, `contact_form`, and `jaot-queue-routing`. Full rule definitions live in `monitoring/prometheus/alert_rules.yml`.

Critical alerts repeat every 1 hour. Warning alerts repeat every 4 hours. Inhibit rules suppress downstream alerts when the root cause is already firing (e.g., `PostgresDown` inhibits all connection/deadlock alerts).

### Monitoring Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GRAFANA_ADMIN_USER` | No | Default: `jaot_admin` |
| `GRAFANA_ADMIN_PASSWORD` | Yes | Grafana admin password |
| `ALERT_EMAIL_RECIPIENT` | Yes | Email address for alert notifications |

The Resend API key must be placed at `secrets/resend_api_key` (file-mounted into Alertmanager at `/run/secrets/resend_api_key`). It is never passed as an environment variable.

---

## Database Migrations

Migrations use Alembic and run as a one-shot container via the `migrate` profile:

```bash
# Run pending migrations
docker compose -f deploy/docker-compose.prod.yml --profile migrate run --rm migrate

# Check current revision (from API container)
docker compose -f deploy/docker-compose.prod.yml exec api alembic -c infra/alembic.ini current
```

Migrations are additive-only. Never DROP or RENAME columns in the same release. Rollback restores images, not schema.

---

## Local Development (without Docker)

```bash
# Start only infrastructure dependencies
docker-compose up -d postgres rabbitmq redis

# Backend
source venv/bin/activate
pip install -r requirements.txt
alembic -c infra/alembic.ini upgrade head
python scripts/ensure_admin_api_key.py
python run.py
```

```bash
# Frontend
cd frontend
npm install
npm run dev   # http://localhost:3000
```

---

## Logs and Diagnostics

```bash
# Tail logs for a specific service
docker compose -f deploy/docker-compose.prod.yml logs -f api
docker compose -f deploy/docker-compose.prod.yml logs -f celery_worker
docker compose -f deploy/docker-compose.prod.yml logs -f prometheus

# Shell into a container
docker compose -f deploy/docker-compose.prod.yml exec api bash
docker compose -f deploy/docker-compose.prod.yml exec postgres psql -U jaot -d jaot

# Restart a service
docker compose -f deploy/docker-compose.prod.yml restart api

# Log rotation
# All containers use json-file driver: max 50MB per file, 10 files retained
```

---

## Troubleshooting

**API does not start** — Verify that postgres, rabbitmq, and redis are healthy:
```bash
docker compose -f deploy/docker-compose.prod.yml ps
docker compose -f deploy/docker-compose.prod.yml logs api
```

**Database connection errors:**
```bash
docker compose -f deploy/docker-compose.prod.yml logs postgres
docker compose -f deploy/docker-compose.prod.yml exec postgres psql -U jaot -d jaot -c "\dt"
```

**Celery does not process tasks:**
```bash
docker compose -f deploy/docker-compose.prod.yml logs celery_worker
# Check RabbitMQ management UI at http://localhost:15672
```

**Frontend does not connect to API** — The production frontend uses `API_PROXY_URL=http://api:8001` and Caddy proxies browser requests from the same origin. Verify Caddy is healthy and the `frontend` network is intact.

**Alertmanager not sending emails** — Verify:
1. `secrets/resend_api_key` exists and contains a valid key
2. `ALERT_EMAIL_RECIPIENT` is set in `.env.production`
3. Check logs: `docker compose -f deploy/docker-compose.prod.yml logs alertmanager`

**Prometheus targets down** — Check scrape targets at `http://localhost:9090/targets`. A target showing `DOWN` means the exporter is unreachable on the `monitoring` or `backend` network.

---

## Security Hardening

All production containers run with:
- `no-new-privileges: true`
- `cap_drop: ALL` (minimal capabilities added back per service)
- `read_only: true` filesystem where possible (API, Celery, frontend, migrate)
- Dedicated `tmpfs` mounts for `/tmp` (64 MB)
- Memory limits enforced per container (32 MB to 4 GB)
- Monitoring ports bound to `127.0.0.1` only
- Docker socket mounted read-only (cAdvisor only)

### Pre-deployment Checklist

- [ ] All `[REQUIRED]` variables set in `.env.production`
- [ ] `secrets/resend_api_key` created with correct permissions
- [ ] Default passwords changed (PostgreSQL, RabbitMQ, Redis, Grafana)
- [ ] `JWT_SECRET` generated with `openssl rand -hex 32`
- [ ] DNS A record for `jaot.io` points to server IP
- [ ] Ports 80 and 443 open in firewall
- [ ] Migrations applied before starting the stack
- [ ] WAL archiving volume (`jaot_wal_archive`) configured for backup
