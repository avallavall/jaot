# Bounded Contexts — Current vs Target

> Modular monolith with 1 context extracted (Solver) and 7 pending. Authoritative reference: [`docs/BOUNDED_CONTEXTS.md`](../../BOUNDED_CONTEXTS.md).

## Diagram

```mermaid
flowchart TB
    subgraph Current["CURRENT STATE (Post-Phase 3)"]
        Extracted["BC1: Solver EXTRACTED<br/>app/domains/solver/"]
        Monolith["BC2–BC7 in Monolith<br/>app/services/<br/>• Marketplace<br/>• Billing<br/>• Identity<br/>• AI Assistant<br/>• Automation<br/>• Observability<br/>BC8: Platform Admin in app/shared/"]
    end

    subgraph Future["TARGET (Post-Phase 7)"]
        Sol["BC1: Solver"]
        Obs["BC7: Observability"]
        AI["BC5: AI Assistant"]
        Id["BC4: Identity"]
        Bill["BC3: Billing"]
        Market["BC2: Marketplace"]
        Auto["BC6: Automation"]
        Admin["BC8: Platform Admin<br/>(never extracted)"]
    end

    subgraph Dependencies["Extraction Order (roadmap §6)"]
        Order["1. Solver (done)<br/>2. Observability (pure leaf)<br/>3. AI Assistant (PSS-only)<br/>4. Identity (fan-in 32+)<br/>5. Billing (depends on Identity)<br/>6. Marketplace (depends on Billing)<br/>7. Automation (orchestrates 4 domains)<br/>8. Platform Admin (singleton, do not extract)"]
    end

    Current -->|Phase 4–7| Future
    Dependencies --> Future

    style Extracted fill:#90EE90
    style Sol fill:#90EE90
    style Admin fill:#FFE4B5
```

## Notes

- **Solver (BC1):** Already extracted in Phase 3 (2026-04-13). Lives in `app/domains/solver/` with its own structure (adapters, routes, services, schemas, tasks).
- **The rest:** Still in `app/services/` as a monolith. The 6 `import-linter` contracts in `pyproject.toml` protect the Solver boundary.
- **Allowed synchronous paths (lint-imports):**
  - `solve_orchestrator` → `credits_service` (pre-pay/refund)
  - `trigger_tasks` → Solver + Credits
  - `featured_placement` → `credits_service`
- **Fire-and-forget:** Any context → `audit_service`, `analytics_service`, `notification_service` (leaves, no inbound dependencies).
- **Not microservices:** Modular monolith — one image, one process, one database. Logical boundaries via directories, `import-linter`, and typed `Protocol`s.
