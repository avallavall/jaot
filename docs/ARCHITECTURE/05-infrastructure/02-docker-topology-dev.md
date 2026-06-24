# Docker Topology — Local (Dev)

> Local stack with `docker-compose.yml` at the repo root. Mirrors prod but with hot-reload, debug enabled, and no resource limits (Docker Desktop ignores cgroups).

## Diagram

```mermaid
graph TB
    Dev["Developer localhost"]

    subgraph DevStack["docker-compose.yml (dev)"]
        DevAPI["API FastAPI<br/>8001 (0.0.0.0)<br/>hot-reload = true<br/>DEBUG = true<br/>workers = 1"]

        DevCelery["celery_worker<br/>-Q jaot_default"]
        DevCeleryDefault["celery-worker-test-default<br/>profile: test"]
        DevCeleryScip["celery-worker-test-scip<br/>profile: test"]
        DevCeleryHighs["celery-worker-test-highs<br/>profile: test"]
        DevBeat["celery_beat<br/>DatabaseScheduler"]

        DevFrontend["Frontend Next.js<br/>3000<br/>target=dev<br/>hot-reload"]

        DevPG["PostgreSQL 18<br/>5432 (127.0.0.1)<br/>jaot_postgres_data"]
        DevRedis["Redis 7<br/>6379 (127.0.0.1)<br/>jaot_redis_data"]
        DevRabbit["RabbitMQ 3<br/>5672 / 15672<br/>jaot_rabbitmq_data"]
        DevQdrant["Qdrant<br/>6333 / 6334<br/>jaot_qdrant_data"]
    end

    subgraph MonitoringCompose["docker-compose.monitoring.yml (optional)"]
        DevProm["Prometheus"]
        DevGraf["Grafana 3001 (127.0.0.1)"]
        DevCeleryExp["celery-exporter 9808 (127.0.0.1)"]
    end

    subgraph Profiles["Optional profiles"]
        Migrate["profile: migrate<br/>Alembic one-shot"]
        Seed["profile: seed<br/>admin + demo templates"]
        Test["profile: test<br/>3 workers routing tests"]
    end

    Dev --> DevAPI
    Dev --> DevFrontend

    DevAPI --> DevPG
    DevAPI --> DevRabbit
    DevAPI --> DevRedis
    DevAPI --> DevQdrant

    DevCelery --> DevRabbit
    DevCeleryDefault --> DevRabbit
    DevCeleryScip --> DevRabbit
    DevCeleryHighs --> DevRabbit

    DevBeat --> DevRabbit
    DevFrontend --> DevAPI

    DevCeleryExp --> DevRabbit
    DevGraf --> DevProm
```

## Profiles

| Profile | Starts | Use |
|--------|---------|-----|
| _default_ | API + celery_worker + beat + frontend + infra | daily development |
| `test` | 3 workers with `-Q jaot_default`, `solve_scip`, `solve_highs` | routing tests (`tests/integration/test_queue_routing.py`) |
| `migrate` | one-shot | `alembic upgrade head` |
| `seed` | one-shot | dev preload (admin + 102 templates + demo models) |

## Notes

- **Hot-reload:** `RELOAD=true` on the API; Next.js with hot-module-reload.
- **Debugging:** `DEBUG=true`; infra exposed on `127.0.0.1` (connect with `psql`, `redis-cli`, DBeaver).
- **No limits:** Docker Desktop ignores `deploy.resources.limits` → allows reproducing without artificial OOM.
- **Optional monitoring:** `docker compose -f deploy/docker-compose.monitoring.yml up` starts a local mini-stack.
