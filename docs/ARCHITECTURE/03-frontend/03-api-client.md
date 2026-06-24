# API Client (`src/lib/api.ts`)

> Centralized HTTP client. Handles auth (Bearer + cookies), retry with exponential backoff, automatic refresh on 401, and 503 maintenance mode detection.

## Refresh flow

```mermaid
sequenceDiagram
    participant C as Component
    participant API as api.ts
    participant Auth as authHeaders()
    participant Back as Backend
    participant R as /auth/refresh

    C->>API: api.login(apiKey)
    API->>Auth: Authorization: Bearer ...
    API->>Back: POST /api/v2/auth/login
    Back-->>API: 200 + cookie JWT
    API-->>C: {user, org}

    Note over C,API: later, the token expires

    C->>API: api.getWorkspace(id)
    API->>Back: GET /api/v2/workspace/{id}
    Back-->>API: 401

    API->>R: POST /auth/refresh (credentials: include)
    R-->>API: 200 + new cookie

    API->>Back: GET /api/v2/workspace/{id} (retry)
    Back-->>API: 200
    API-->>C: data
```

## Request pipeline

```mermaid
flowchart LR
    Req["request(path, options)"]
    Req --> URL["buildUrl + query params"]
    URL --> Headers["headers = {Content-Type, ...authHeaders()}"]
    Headers --> Fetch["fetch(url, credentials: include)"]

    Fetch --> OK["res.ok?"]
    OK -->|yes, 204| Return204["return undefined"]
    OK -->|yes, data| JSON["return res.json()"]

    OK -->|no| Retry["isRetryableStatus?"]
    Retry -->|yes &lt; max| Wait["sleep backoff"]
    Wait --> Fetch

    Retry -->|503 maintenance| Event["dispatch jaot:maintenance"]
    Event --> Throw["throw ApiError"]

    Retry -->|401 + !_retried| Refresh["refreshAccessToken()"]
    Refresh --> Retry2["request(path, _retried=true)"]
    Retry2 --> Fetch

    Retry -->|no| ParseErr["extract error body"]
    ParseErr --> Throw
```

## Key mechanisms

| Mechanism | Description |
|-----------|-------------|
| `authHeaders()` | adds `Authorization: Bearer <apiKey>` if a key exists in `localStorage` |
| `refreshAccessToken()` | POST `/auth/refresh` with a singleton `refreshPromise` to avoid race conditions |
| 401 handling | auto-refresh + retry with `_retried` flag (no infinite loop) |
| 503 handling | parses `detail.status === "maintenance"` → dispatches event → `MaintenanceBanner` reacts |
| Exponential backoff | 1 s, 2 s, 4 s for retryable 5xx |
| `ApiError` class | status + message + detail (Pydantic errors) |

## Tech debt

- **Unsynchronized dual auth:** `localStorage` (Bearer) + cookie (JWT). A full logout should clear both; today it only clears localStorage.
- **No timeout on `fetch`:** requests can hang indefinitely. An `AbortController` with a timeout should be used.
- **No deduplication:** two components with the same `useEffect` fire two identical requests. A candidate for SWR / React Query if this grows.

## Referenced files

- `frontend/src/lib/api.ts` — ~1500 lines (`request`, `authHeaders`, `refreshAccessToken`, `ApiError`, all typed endpoints).
- `frontend/src/contexts/AuthContext.tsx` — `validateSession()` on mount + coordinated `logout()`.
