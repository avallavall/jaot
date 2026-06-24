# Backend Layered Architecture

> Modular FastAPI with dependency injection, rate limiting, authentication, and asynchronous orchestration via Celery.

## Diagram

```mermaid
flowchart TB
    subgraph HTTPRequest["HTTP Request"]
        Client["Client (API Key + JWT)"]
    end

    subgraph FastAPIMW["FastAPI Middleware (outer → inner)"]
        CORS["CORS + GZip"]
        Auth["ASGIAuthMiddleware"]
        Maintenance["MaintenanceMiddleware"]
        Security["SecurityHeadersMiddleware"]
        BodyLimit["BodyLimitMiddleware"]
        ReqID["RequestIdMiddleware"]
    end

    subgraph DepsLayer["Dependency Injection (app/api/deps.py)"]
        CurrentUser["get_current_user"]
        DBSession["get_db"]
        RateLimiter["check_rate_limit"]
        OrgContext["get_current_organization"]
        WorkspaceRole["require_workspace_role"]
    end

    subgraph RoutersLayer["API Route Handlers (app/api/v2/routes/)"]
        Solve["POST /solve"]
        Models["GET /models/:id"]
        Admin["POST /admin/settings"]
        Profiles["GET /profiles/me"]
    end

    subgraph ServiceLayer["Business Logic (app/services/ + app/domains/solver/)"]
        SolveOrch["SolveOrchestrator"]
        CreditsService["CreditsService"]
        SolverService["SolverService"]
        SettingsService["PlatformSettingsService"]
        Analytics["AnalyticsService"]
    end

    subgraph AdapterLayer["Domain Adapters (app/domains/solver/adapters/)"]
        Protocol["SolverAdapter Protocol"]
        SCIP["SCIPAdapter"]
        Highs["HighsAdapter"]
    end

    subgraph ProducerPath["Celery Producer Path"]
        Producer["apply_async(queue=...)"]
        RabbitMQ["RabbitMQ Broker"]
    end

    subgraph PersistenceLayer["Persistence Layer"]
        SQLAlchemy["SQLAlchemy 2.0 ORM (app/models/)"]
        PostgreSQL["PostgreSQL Database"]
    end

    subgraph RedisLayer["Cache & Rate-Limiting"]
        Redis["Redis (rate_limiter, WebSocket pub/sub)"]
    end

    Client --> CORS
    CORS --> Auth
    Auth --> Maintenance
    Maintenance --> Security
    Security --> BodyLimit
    BodyLimit --> ReqID

    ReqID --> CurrentUser
    ReqID --> DBSession
    ReqID --> RateLimiter
    CurrentUser --> OrgContext
    OrgContext --> WorkspaceRole

    CurrentUser --> Solve
    DBSession --> Models
    RateLimiter --> Admin
    Solve --> SolveOrch
    Models --> SolverService
    Admin --> SettingsService
    Profiles --> Analytics

    SolveOrch --> CreditsService
    SolveOrch --> SolverService
    SolverService --> Protocol
    Protocol --> SCIP
    Protocol --> Highs

    SolveOrch --> Producer
    Producer --> RabbitMQ

    SolveOrch --> SQLAlchemy
    SettingsService --> SQLAlchemy
    Analytics --> SQLAlchemy

    SQLAlchemy --> PostgreSQL

    RateLimiter -.->|sliding window| Redis
    Producer -.->|WebSocket events| Redis
```

## Notes

- **Middlewares:** Pure ASGI, never `BaseHTTPMiddleware`. Auth always enabled (ADR-001).
- **Dependencies:** The 4 main ones injected in `app/api/deps.py` — `DBSession`, `CurrentUser`, `CurrentOrg`, `AdminUser`.
- **Rate-limiting:** `check_rate_limit(org_id, limit/min, limit/day)` on every endpoint — actual implementation in `app/shared/core/rate_limiter.py`.
- **ORM:** Typed SQLAlchemy 2.0 — `Mapped[str]`, `mapped_column(...)` in `app/models/`.
- **Celery:** Producer in FastAPI (injects `queue=...` via `resolve_queue()`), consumer in separate workers.
- **Config:** Two tiers — `app/config.py` (immutable infra) + `PlatformSettingsService` (runtime-mutable business config).
