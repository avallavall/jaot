# Celery Queues + Workers — Post-Phase-6

> Single producer (API) · 4 queues in RabbitMQ · 4 specialized workers with a runtime guard (`SOLVER_QUEUE` env var). Hexaly worker is profile-gated (`profiles: ["hexaly"]`).

## Diagram

```mermaid
graph LR
    API["FastAPI (producer)"]

    Router["queue_routing.py<br/>SOLVER_QUEUE_MAP<br/>{scip→solve_scip, highs→solve_highs, hexaly→solve_hexaly}"]

    Broker["RabbitMQ<br/>amqp://rabbitmq:5672"]

    subgraph Queues["4 RabbitMQ queues"]
        DefaultQ["jaot_default<br/>(email, webhooks, financial, cron)"]
        ScipQ["solve_scip"]
        HighsQ["solve_highs"]
        HexalyQ["solve_hexaly"]
    end

    subgraph Workers["4 specialized workers"]
        DefaultW["celery_worker_default<br/>-Q jaot_default<br/>SOLVER_QUEUE=jaot_default<br/>256M / 0.25 CPU<br/>concurrency=2"]
        ScipW["celery_worker_scip<br/>-Q solve_scip<br/>SOLVER_QUEUE=solve_scip<br/>3G / 2.0 CPU<br/>concurrency=2"]
        HighsW["celery_worker_highs<br/>-Q solve_highs<br/>SOLVER_QUEUE=solve_highs<br/>1G / 1.0 CPU<br/>concurrency=1"]
        HexalyW["celery_worker_hexaly<br/>-Q solve_hexaly<br/>SOLVER_QUEUE=solve_hexaly<br/>2G / 1.0 CPU<br/>concurrency=1<br/>profiles: [hexaly]"]
    end

    Guard["_assert_queue_match()<br/>runtime guard"]

    DB["PostgreSQL<br/>task results + execution state"]
    Mismatch["SolverQueueMismatchError"]

    API -->|apply_async queue=solve_scip| Router
    API -->|apply_async queue=solve_highs| Router
    API -->|send_email / webhook_notify| Router
    Router --> Broker

    Broker --> DefaultQ
    Broker --> ScipQ
    Broker --> HighsQ

    DefaultQ --> DefaultW
    ScipQ --> ScipW
    HighsQ --> HighsW
    HexalyQ --> HexalyW

    DefaultW --> Guard
    ScipW --> Guard
    HighsW --> Guard
    HexalyW --> Guard

    Guard -->|mismatch| Mismatch
    Guard -->|match| DB
```

## Routing — key rules

**Producer** (FastAPI):
1. `resolve_queue(solver_name)` → `"solve_scip"` / `"solve_highs"` / `"solve_hexaly"`.
2. `apply_async(kwargs=..., queue=target_queue)`.
3. If `solver_name` is unknown → `SolverNotFoundError` → HTTP 422 + refund.

**Consumer** (worker container):
1. Starts with `-Q solve_scip` (CLI).
2. Reads `SOLVER_QUEUE=solve_scip` from the env.
3. `_assert_queue_match(solver_name)` compares `SOLVER_QUEUE` against the requested solver.
4. Mismatch → `SolverQueueMismatchError` with a non-leaking message; the task fails immediately (no requeue, since it is deterministic).

## Current routing map

```python
# app/domains/solver/queue_routing.py
SOLVER_QUEUE_MAP = {
    "scip": "solve_scip",
    "highs": "solve_highs",
    "hexaly": "solve_hexaly",  # Active — profile-gated worker in docker-compose.prod.yml
}
```

Hexaly is already wired in the routing map. Activate on a deployment with `--profile hexaly` and a platform license at `/etc/jaot/hexaly.lic`.

## Notes

- **Defense in depth:** routing-level (`-Q`) + runtime guard (`SOLVER_QUEUE` env). Two independent layers.
- **Acks late:** `task_acks_late=True` + `task_reject_on_worker_lost=True` → zero loss on crashes; hung tasks are redelivered.
- **Monitoring:** `celery_queue_length{queue=~"solve_.*"}` feeds the `solver-workers.json` dashboard and the `SolverQueueBacklogWarn/Critical` alerts.
- **Hexaly (D-16, D-17):** active in `SOLVER_QUEUE_MAP`; worker is profile-gated (`profiles: ["hexaly"]`) with 2G memory limit. `SOLVER_QUEUE_MAP` remains the single extension point for future solvers.
