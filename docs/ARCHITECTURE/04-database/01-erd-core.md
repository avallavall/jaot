# ERD Core — Identity + Model + Execution

> Core platform entities: User, Organization, Workspace, APIKey, RefreshToken, OptimizationModel, ModelExecution. Multi-tenant org-scoped.

> **Note (ADR-008):** the billing entities that used to live here (`credit_transactions`,
> `workspace_credit_pools`, `invoices`, plus the credit/Stripe columns on `organizations`
> and `model_executions`) were removed from the application. The migration
> `20260924_drop_billing_tables` dropped their 9 tables and 13 columns from the database.

## Diagram

```mermaid
erDiagram
    ORGANIZATION ||--o{ USER : "owns_users"
    ORGANIZATION ||--o{ APIKEY : "has_api_keys"
    ORGANIZATION ||--o{ WORKSPACE : "has_workspaces"
    ORGANIZATION ||--o{ REFRESHTOKEN : "has_refresh_tokens"
    ORGANIZATION ||--o{ OPTIMIZATION_MODEL : "owns_models"
    ORGANIZATION ||--o{ MODEL_EXECUTION : "executes_models"

    USER ||--o{ REFRESHTOKEN : "auth_tokens"
    USER ||--o{ WORKSPACE_MEMBER : "workspace_roles"

    WORKSPACE ||--o{ WORKSPACE_MEMBER : "has_members"
    WORKSPACE ||--o{ WORKSPACE_REMOVAL : "removed_members"

    OPTIMIZATION_MODEL ||--o{ MODEL_EXECUTION : "spawns_executions"

    ORGANIZATION : string id (pk) "org_*"
    ORGANIZATION : string name
    ORGANIZATION : string plan "free|starter|pro|business (limits only)"
    ORGANIZATION : bool is_active

    USER : string id (pk) "usr_*"
    USER : string email (unique)
    USER : string name "the one name every page shows"
    USER : string organization_id (fk)
    USER : string password_hash "nullable for API-key-only"
    USER : bool email_verified
    USER : string role "admin|member"

    APIKEY : string id (pk) "key_*"
    APIKEY : string organization_id (fk)
    APIKEY : string key_hash "SHA-256"
    APIKEY : datetime expires_at "nullable"

    REFRESHTOKEN : string id (pk)
    REFRESHTOKEN : string user_id (fk)
    REFRESHTOKEN : string organization_id (fk)
    REFRESHTOKEN : string token_hash
    REFRESHTOKEN : datetime revoked_at "nullable"

    WORKSPACE : string id (pk) "ws_*"
    WORKSPACE : string organization_id (fk)
    WORKSPACE : string name
    WORKSPACE : string description "nullable"
    WORKSPACE : bool is_active

    WORKSPACE_MEMBER : string id (pk)
    WORKSPACE_MEMBER : string workspace_id (fk)
    WORKSPACE_MEMBER : string user_id (fk)
    WORKSPACE_MEMBER : string role "admin|editor|solver|viewer"

    WORKSPACE_REMOVAL : string id (pk) "wkr_*"
    WORKSPACE_REMOVAL : string workspace_id (fk)
    WORKSPACE_REMOVAL : string user_id (fk)
    WORKSPACE_REMOVAL : datetime removed_at "an invite created before it is refused"

    OPTIMIZATION_MODEL : string id (pk) "opt_*"
    OPTIMIZATION_MODEL : string organization_id (fk)
    OPTIMIZATION_MODEL : string name
    OPTIMIZATION_MODEL : string category

    MODEL_EXECUTION : string id (pk) "exe_*"
    MODEL_EXECUTION : string organization_id (fk)
    MODEL_EXECUTION : string model_id (fk)
    MODEL_EXECUTION : string status "pending|running|completed|failed"
    MODEL_EXECUTION : float objective_value "result"
```
