# Quickstart

Get from zero to your first solved optimization problem in under 15 minutes.

---

## Prerequisites

- Git
- Either **Docker + Docker Compose** (recommended) or **Python 3.12** with a local PostgreSQL instance

---

## Path A — Docker (recommended)

### 1. Clone and configure

```bash
git clone https://github.com/avallavall/jaot.git
cd jaot
cp .env.example .env
```

The defaults in `.env.example` work out of the box with Docker. No changes needed for a local trial.

### 2. Start all services

```bash
docker compose up -d
```

This starts: PostgreSQL, RabbitMQ, Redis, Qdrant (vector search for the RAG assistant), the API server (port 8001), the Celery worker + beat, and the Next.js frontend (port 3000).

Check that everything is up:

```bash
docker compose ps
curl http://localhost:8001/api/v2/health
```

### 3. Log in

On the first start against an empty database the API runs migrations, seeds
the catalog with 102 templates, and creates your admin user from the `SEED_ADMIN_*`
values in `.env` (see `.env.example` — change the password). Open
http://localhost:3000 and log in with those credentials.

Didn't set `SEED_ADMIN_*` before the first start? Create the admin manually:

```bash
docker compose exec -e ADMIN_EMAIL=you@example.com -e ADMIN_PASSWORD=pick-a-passphrase \
  api python -m app.shared.db.seed_admin
```

### 4. Create an admin API key

```bash
docker compose exec api python scripts/ensure_admin_api_key.py
```

Mints an API key for the first-run admin (falls back to creating one if none
exists). Copy the printed API key — it is only shown once.

### 5. Solve your first problem

```bash
export API_KEY="<paste-your-key-here>"

curl -X POST http://localhost:8001/api/v2/solve \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "simple-lp",
    "variables": [
      {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
      {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 10}
    ],
    "objective": {
      "sense": "maximize",
      "expression": "3*x + 5*y"
    },
    "constraints": [
      {"name": "c1", "expression": "x + 2*y <= 12"},
      {"name": "c2", "expression": "2*x + y <= 10"}
    ]
  }'
```

Expected response (abbreviated):

```json
{
  "status": "optimal",
  "execution_id": "exe_...",
  "objective_value": 31.666,
  "variables": [
    {"name": "x", "value": 2.666, "type": "continuous"},
    {"name": "y", "value": 4.666, "type": "continuous"}
  ],
  "solution": {"x": 2.666, "y": 4.666},
  "solve_time_seconds": 0.003,
  "credits_used": 1
}
```

### 6. Open the UI

Visit [http://localhost:3000](http://localhost:3000) and log in with your admin credentials to explore the dashboard, model catalog, and execution history.

---

## Path B — Local development (venv)

Use this path if you want to run the backend outside Docker, e.g. for faster iteration.

### 1. Clone and configure

```bash
git clone https://github.com/avallavall/jaot.git
cd jaot
cp .env.example .env
```

Edit `.env` and set:

```
DATABASE_URL=postgresql://jaot:jaot@localhost:5432/jaot
CELERY_BROKER_URL=amqp://jaot:jaot@localhost:5672//
REDIS_URL=redis://localhost:6379/0
```

Adjust credentials to match your local PostgreSQL / RabbitMQ / Redis instances. Redis can be left empty for an in-memory fallback in development.

### 2. Start infrastructure services

```bash
docker compose up -d postgres rabbitmq
```

Or use existing local instances if you have them.

### 3. Set up Python environment

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Initialize the database

```bash
alembic -c infra/alembic.ini upgrade head
```

(Skippable if you start the API at least once with `DEBUG=True` — it
auto-migrates on boot.)

### 5. Create an admin API key

```bash
python scripts/ensure_admin_api_key.py
```

You can override defaults with environment variables:

```bash
ENSURE_ADMIN_EMAIL=me@example.com \
ENSURE_ADMIN_ORG_NAME="My Org" \
python scripts/ensure_admin_api_key.py
```

### 6. Start the API server

```bash
python run.py
# Server starts on http://localhost:8001
```

### 7. Start the Celery worker (optional — needed for async execution)

Open a second terminal:

```bash
source venv/bin/activate
celery -A app.shared.core.celery_app worker --loglevel=info
```

### 8. Start the frontend (optional)

```bash
cd frontend
npm install
npm run dev
# Frontend starts on http://localhost:3000
```

### 9. Solve your first problem

Same `curl` command as in Path A, step 5.

---

## What's next

- Browse the API docs at `http://localhost:8001/docs` (Swagger UI) for all available endpoints
- Explore the [Model Catalog](http://localhost:3000/en/catalog) to activate pre-built optimization templates

---

## Optional: Hexaly solver (commercial, BYOL)

Hexaly is a commercial metaheuristic solver well-suited for quadratic / non-convex problems. JAOT supports it under a **Bring-Your-Own-License** model — the deploy operator mounts a single instance-level `.lic` file issued by Hexaly into the `celery_worker_hexaly` container.

The **default worker image does NOT include** the Hexaly SDK. To enable Hexaly solves in production:

1. **Obtain a `.lic` file** from Hexaly support (one file per deployment instance).
2. **Place it on the deploy host** at `/etc/jaot/hexaly.lic` (root:root, permissions 0600) and confirm the bind-mount in `deploy/docker-compose.prod.yml` under `celery_worker_hexaly`.
3. **Ensure the production deploy includes `celery_worker_hexaly`** in `deploy/docker-compose.prod.yml`. The service uses the `jaot-worker-hexaly` image built by the `build-worker-hexaly` CI step.
4. **Restart the Hexaly worker** (`docker compose ... up -d --no-deps celery_worker_hexaly`) and confirm the startup log shows `Platform Hexaly license loaded`.
5. **Verify** that `GET /api/v2/solvers/available` lists `hexaly` (the endpoint reports the SDK-import gate — not license state).
6. **Solve:** pass `solver_name="hexaly"` (or leave `solver_name="auto"` and let the auto-router pick Hexaly for quadratic problems).

The Hexaly integration path is code-complete and follows Hexaly's documented Python API and platform-license model, but has not yet been validated end-to-end with a real license; the first activation should run the steps in `deploy/RUNBOOK-hexaly-verification.md`.

**Without Hexaly:** the `celery_worker_hexaly` service is optional — deployments without a Hexaly license can scale it to zero without affecting the rest of the stack.

Disaster recovery + license rotation: `deploy/DISASTER-RECOVERY.md` §6.

---

## Running Tests

Tests run against real PostgreSQL (database `jaot_test`, same instance). Auth is always active — tests use real API keys.

```bash
# Start test database
docker compose up -d postgres

# Backend tests
pytest tests/ -v

# Frontend tests
cd frontend && npm run test

# E2E tests
cd frontend && npm run test:e2e
```

Key fixtures: `authenticated_client` and `admin_client` provide real API key authentication. Never mock the database or disable auth.

---

## Production Deployment

See [Deployment Guide](../operations/DEPLOYMENT.md) and [Disaster Recovery](../../deploy/DISASTER-RECOVERY.md) for production setup on a self-hosted server.

---

## Commands reference

<!-- AUTO-GENERATED: frontend commands from frontend/package.json — do not edit by hand. Regenerate via /update-docs. -->

### Frontend (run inside `frontend/`)

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Next.js dev server (webpack) on port 3000 |
| `npm run build` | Production build (webpack). Pre-step fetches OpenAPI and regenerates types when API is running |
| `npm start` | Start Next.js production server |
| `npm run lint` | Run ESLint on the frontend tree |
| `npm run check-i18n` | Verify i18n keys are consistent across all 5 locales |
| `npm run test` | Vitest unit tests (NODE_OPTIONS max-old-space-size=4096) |
| `npm run test:watch` | Vitest watch mode |
| `npm run test:e2e` | Playwright E2E tests (headless) |
| `npm run test:e2e:ui` | Playwright E2E tests with the interactive UI runner |
| `npm run generate-types` | Regenerate TypeScript API types from `../openapi.json` |
| `npm run generate-search` | Rebuild the static search index |
| `npm run regenerate` | Full regeneration: fetch OpenAPI → regen types → rebuild search index |
| `npm run check-types` | Regenerate API types and fail if the result diverges from committed `api.ts` |

<!-- /AUTO-GENERATED -->

<!-- AUTO-GENERATED: backend commands derived from pyproject.toml + scripts/ — do not edit by hand. Regenerate via /update-docs. -->

### Backend (project root, venv activated)

| Command | Description |
|---------|-------------|
| `python run.py` | Start the FastAPI server on `HOST:PORT` from `.env` (default 0.0.0.0:8001) |
| `pytest` | Run backend tests against real PostgreSQL (`jaot_test` DB). `addopts` auto-excludes `slow` and `load` markers |
| `pytest -m unit` | Only pure-unit tests (no I/O) |
| `pytest -m integration` | Only integration tests (external services) |
| `ruff check app/` | Lint with ruff (line length 100, project-level ignores in `pyproject.toml`) |
| `ruff format app/` | Format Python files with ruff (replaces black + isort) |
| `lint-imports` | Validate import-linter contracts (6 contracts — domain boundaries + pyscipopt isolation) |
| `alembic -c infra/alembic.ini upgrade head` | Apply DB migrations |
| `alembic -c infra/alembic.ini revision --autogenerate -m "desc"` | Create a new migration from model changes |
| `celery -A app.shared.core.celery_app worker --loglevel=info` | Start a Celery worker (requires RabbitMQ) |
| `python -m app.shared.db.seed_admin` | Create/promote an admin user (`ADMIN_EMAIL`/`ADMIN_PASSWORD` env) |
| `python scripts/ensure_admin_api_key.py` | Mint an admin API key (creates the admin if missing); prints the key |
| `python scripts/seed_dev.py` | Seed development fixtures |
| `python scripts/export_openapi.py` | Dump the OpenAPI schema to `openapi.json` |

<!-- /AUTO-GENERATED -->

---

## Environment variables

<!-- AUTO-GENERATED: from .env.example — do not edit by hand. Regenerate via /update-docs. -->

Only **infrastructure** variables live in `.env`. Business configuration (plans, LLM, Stripe, SMTP, feature flags, rate limits) is stored in the `platform_settings` DB table and edited via the admin panel.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | **yes** | `postgresql://jaot:jaot@localhost:5432/jaot` | PostgreSQL connection string |
| `DB_POOL_SIZE` | no | `20` | SQLAlchemy QueuePool base size |
| `DB_MAX_OVERFLOW` | no | `10` | SQLAlchemy QueuePool overflow above base |
| `DB_POOL_RECYCLE` | no | `3600` | Recycle connections after N seconds |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | no | `jaot` / `jaot` / `jaot` | Used by `docker-compose`, not the app itself |
| `REDIS_URL` | no | `redis://localhost:6379/0` | Rate limiter + Celery result backend. Empty → in-memory fallback (dev only) |
| `REDIS_PASSWORD` | no | *(empty)* | Redis AUTH if configured |
| `CELERY_BROKER_URL` | **yes** | `amqp://jaot:jaot@localhost:5672//` | RabbitMQ AMQP URL for Celery task dispatch |
| `CELERY_RESULT_EXPIRES` | no | `604800` | Result backend TTL in seconds (7 days) |
| `CELERY_MAX_RETRIES` | no | `3` | Max retries per failed Celery task |
| `CELERY_DEFAULT_RETRY_DELAY` | no | `300` | Retry backoff base in seconds |
| `RABBITMQ_USER` / `RABBITMQ_PASS` | no | `jaot` / `jaot` | Used by `docker-compose` |
| `JWT_SECRET` | **yes (prod)** | *(empty)* | 256-bit secret for JWT signing. Required when `DEBUG=False`. Generate via `openssl rand -hex 32` |
| `DEBUG` | no | `True` | Dev-mode flag: auto-reload, verbose errors, auto-JWT |
| `HOST` | no | `0.0.0.0` | Bind address for uvicorn |
| `PORT` | no | `8001` | Listen port for the API |
| `WORKERS` | no | `1` | Uvicorn worker count (prod: set > 1) |
| `RELOAD` | no | `True` | Enable hot reload on file change |
| `FRONTEND_URL` | **yes** | `http://localhost:3000` | Used for CORS, email links, OAuth callbacks |
| `ALLOWED_ORIGINS` | no | `["http://localhost:3000"]` | JSON-array whitelist for CORS (explicit, never wildcard) |
| `QDRANT_URL` | no | `http://localhost:6333` | Vector DB for RAG. Leave empty to disable RAG |
| `QDRANT_API_KEY` | no | *(empty)* | Qdrant auth if the deployment uses it |
| `GRAFANA_ADMIN_PASSWORD` | no | *(empty)* | `docker-compose` monitoring stack only |

<!-- /AUTO-GENERATED -->
