# Celery Flow — Producer → Broker → Worker → Result

> 3-layer asynchronous architecture: producer (FastAPI), RabbitMQ broker, workers specialized per solver.

## Sequence — One solve end-to-end

```mermaid
sequenceDiagram
    participant Client as Client
    participant API as FastAPI<br/>/solve
    participant Gate as solve_maintenance_gate
    participant Credits as CreditsService
    participant Resolve as resolve_queue()
    participant Broker as RabbitMQ
    participant Worker as Worker SCIP<br/>SOLVER_QUEUE=solve_scip
    participant Adapter as SCIPAdapter
    participant Redis as Redis<br/>result backend
    participant WS as WebSocket<br/>pub/sub

    Client->>API: POST /solve (problem, solver='scip')
    API->>Gate: Depends(solve_maintenance_gate)
    Gate-->>API: ok (flag=false)
    API->>Credits: deduct prepayment
    Credits-->>API: ok
    API->>Resolve: resolve_queue('scip')
    Resolve-->>API: 'solve_scip'
    API->>Broker: apply_async(queue='solve_scip')
    Broker-->>API: task_id
    API-->>Client: 202 Accepted {execution_id, task_id}

    Broker->>Worker: deliver solve_async
    Worker->>Worker: _assert_queue_match('scip') ✓
    Worker->>Adapter: solve(problem)
    Adapter->>Adapter: build SCIP model + pyscipopt
    Adapter-->>Worker: OptimizationResult
    Worker->>Redis: store result (TTL 7d)
    Worker->>WS: publish ws:execution:{id}

    Client->>API: GET /solve/async/{task_id}
    API->>Redis: get result
    API-->>Client: 200 {status, objective, solution}
```

## Infrastructure topology

```mermaid
flowchart LR
    subgraph FastAPICluster["FastAPI (producer)"]
        Endpoint["POST /solve"]
        SolveOrch["SolveOrchestrator"]
        CeleryProducer["celery_app"]
    end

    subgraph RabbitMQBroker["RabbitMQ"]
        Exchange["default exchange"]
        Q1["solve_scip"]
        Q2["solve_highs"]
        Q3["default"]
    end

    subgraph WorkerPool["Workers (separate containers)"]
        W1["celery_worker_scip<br/>3G / 2.0 CPU"]
        W2["celery_worker_highs<br/>1G / 1.0 CPU"]
        W3["celery_worker_default<br/>256M / 0.25 CPU"]
    end

    subgraph Storage["Backends"]
        Redis["Redis<br/>result + rate limit + pub/sub"]
        PostgreSQL["PostgreSQL<br/>execution logs + model history"]
    end

    Endpoint --> SolveOrch
    SolveOrch -->|apply_async queue=solve_scip| CeleryProducer
    CeleryProducer --> Exchange

    Exchange --> Q1
    Exchange --> Q2
    Exchange --> Q3

    Q1 --> W1
    Q2 --> W2
    Q3 --> W3

    W1 --> Redis
    W2 --> Redis
    W3 --> Redis
    W1 --> PostgreSQL
    W3 --> PostgreSQL
    Redis -.->|WS events| Endpoint
```

## Maintenance mode (SOLVE_MAINTENANCE_MODE)

```mermaid
flowchart TB
    Endpoint["POST /solve"]
    Gate["solve_maintenance_gate<br/>Depends()"]
    PSS["PSS.get_bool<br/>SOLVE_MAINTENANCE_MODE"]
    Reject["HTTP 503<br/>Retry-After: 600"]
    Proceed["continue pipeline"]

    Endpoint --> Gate
    Gate --> PSS
    PSS -->|true| Reject
    PSS -->|false| Proceed
    Reject --> Client["Client + exponential backoff"]
```

## Celery configuration (`app/shared/core/celery_app.py`)

- **Broker:** RabbitMQ (AMQP) — `CELERY_BROKER_URL`
- **Result backend:** Redis with 7-day TTL
- **Acks:** `task_acks_late=True` (ack after completion)
- **Requeue:** `task_reject_on_worker_lost=True` (retries if the worker dies)
- **Static routes:** only `financial_tasks` → `default` (Beat scheduler)
- **Dynamic routes:** `solve_async` → `resolve_queue(solver_name)` in the producer
- **Events:** `worker_send_task_events=True` + `task_send_sent_event=True` → celery-exporter to Prometheus

## Notes

- **`_assert_queue_match`:** first statement inside the outer `try` in `solve_async` and `solve_model_async` (`solve_tasks.py`). Reads `os.getenv("SOLVER_QUEUE")` — env var injected by `docker-compose.prod.yml`. Raises `SolverQueueMismatchError` on mismatch, with a non-leaking message.
- **WebSocket:** Redis relays `ws:execution:{execution_id}` events for real-time updates to the client.
- **Retry TTL:** results expire after 7 days → GET returns 404.
- **Transactionality:** Credits pre-deducted; automatic refund on `SolverError` + entry in `audit_log`.
