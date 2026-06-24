# ERD Core — Identity + Model + Billing

> Core platform entities: User, Organization, Workspace, APIKey, RefreshToken, OptimizationModel, ModelExecution, Billing. Multi-tenant org-scoped.

## Diagram

```mermaid
erDiagram
    ORGANIZATION ||--o{ USER : "owns_users"
    ORGANIZATION ||--o{ APIKEY : "has_api_keys"
    ORGANIZATION ||--o{ WORKSPACE : "has_workspaces"
    ORGANIZATION ||--o{ REFRESHTOKEN : "has_refresh_tokens"
    ORGANIZATION ||--o{ CREDIT_TRANSACTION : "tracks_credits"
    ORGANIZATION ||--o{ OPTIMIZATION_MODEL : "owns_models"
    ORGANIZATION ||--o{ MODEL_EXECUTION : "executes_models"
    ORGANIZATION ||--o{ WORKSPACE_CREDITS : "manages_pools"
    ORGANIZATION ||--o{ INVOICE : "receives_invoices"
    
    USER ||--o{ REFRESHTOKEN : "auth_tokens"
    USER ||--o{ WORKSPACE_MEMBER : "workspace_roles"
    
    WORKSPACE ||--o{ WORKSPACE_MEMBER : "has_members"
    WORKSPACE ||--o{ WORKSPACE_CREDITS : "allocates_credits"
    
    OPTIMIZATION_MODEL ||--o{ MODEL_EXECUTION : "spawns_executions"
    
    ORGANIZATION : string id (pk) "org_*"
    ORGANIZATION : string name
    ORGANIZATION : string plan "free|starter|pro|business"
    ORGANIZATION : int credits_balance
    ORGANIZATION : int credits_subscription
    ORGANIZATION : int credits_earned "withdrawable"
    ORGANIZATION : string stripe_customer_id
    ORGANIZATION : string stripe_connect_account_id "seller account"
    ORGANIZATION : bool is_frozen "chargeback protection"
    
    USER : string id (pk) "usr_*"
    USER : string email (unique)
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
    
    OPTIMIZATION_MODEL : string id (pk) "opt_*"
    OPTIMIZATION_MODEL : string organization_id (fk)
    OPTIMIZATION_MODEL : string name
    OPTIMIZATION_MODEL : string category
    
    MODEL_EXECUTION : string id (pk) "exe_*"
    MODEL_EXECUTION : string organization_id (fk)
    MODEL_EXECUTION : string model_id (fk)
    MODEL_EXECUTION : string status "pending|running|completed|failed"
    MODEL_EXECUTION : int credits_consumed
    MODEL_EXECUTION : float objective_value "result"
    
    CREDIT_TRANSACTION : string id (pk) "ctx_*"
    CREDIT_TRANSACTION : string organization_id (fk)
    CREDIT_TRANSACTION : string transaction_type "purchase|execution|sale_earning|withdrawal|..."
    CREDIT_TRANSACTION : int credits_amount
    CREDIT_TRANSACTION : int balance_after
    CREDIT_TRANSACTION : string reference_type "nullable"
    CREDIT_TRANSACTION : string reference_id "nullable"
    
    WORKSPACE_CREDITS : string workspace_id (pk/fk)
    WORKSPACE_CREDITS : int allocated
    WORKSPACE_CREDITS : int consumed
    
    INVOICE : string id (pk) "inv_*"
    INVOICE : string organization_id (fk)
    INVOICE : string invoice_number "unique"
    INVOICE : float total_eur
    INVOICE : string status "draft|sent|paid|..."
```
