# ERD Platform — Admin, Observability, Settings

> Infrastructure entities: PlatformSetting, PlatformSettingAudit, AuditLog, AnalyticsEvent, Notification, UsageRecord.

## Diagram

```mermaid
erDiagram
    ORGANIZATION ||--o{ AUDIT_LOG : "workspace_audits"
    ORGANIZATION ||--o{ NOTIFICATION : "receives_notifications"
    ORGANIZATION ||--o{ USAGE_RECORD : "has_usage"
    ORGANIZATION ||--o{ ANALYTICS_EVENT : "generates_events"
    
    USER ||--o{ AUDIT_LOG : "actor_in_audit"
    USER ||--o{ NOTIFICATION : "receives_notification"
    USER ||--o{ NOTIFICATION_PREFERENCE : "configures_prefs"
    USER ||--o{ ANALYTICS_EVENT : "triggers_events"
    
    WORKSPACE ||--o{ AUDIT_LOG : "audited_in_workspace"
    
    PLATFORM_SETTING ||--o{ PLATFORM_SETTING_AUDIT : "history"
    
    ORGANIZATION : string id (pk)
    ORGANIZATION : string name
    
    USER : string id (pk)
    USER : string email
    USER : string organization_id (fk)
    
    WORKSPACE : string id (pk)
    WORKSPACE : string organization_id (fk)
    WORKSPACE : string name
    
    AUDIT_LOG : string id (pk)
    AUDIT_LOG : string workspace_id (fk)
    AUDIT_LOG : string actor_id (fk to User)
    AUDIT_LOG : string action "create|update|delete|share|..."
    AUDIT_LOG : string target_type "model|trigger|document|..."
    AUDIT_LOG : string target_id
    AUDIT_LOG : json before_state "nullable"
    AUDIT_LOG : json after_state "nullable"
    AUDIT_LOG : datetime created_at "indexed"
    
    NOTIFICATION : string id (pk) "notif_*"
    NOTIFICATION : string organization_id (fk)
    NOTIFICATION : string user_id (fk)
    NOTIFICATION : string type "low_credits|execution_complete|..."
    NOTIFICATION : string title
    NOTIFICATION : string body
    NOTIFICATION : string action_url "nullable"
    NOTIFICATION : bool is_read
    NOTIFICATION : datetime created_at
    
    NOTIFICATION_PREFERENCE : string user_id (pk/fk)
    NOTIFICATION_PREFERENCE : string notification_type (pk)
    NOTIFICATION_PREFERENCE : bool enabled
    
    USAGE_RECORD : string id (pk) "usage_*"
    USAGE_RECORD : string organization_id (fk)
    USAGE_RECORD : string problem_type "linear|mip|qp|..."
    USAGE_RECORD : int credits_used
    USAGE_RECORD : float execution_time_ms
    USAGE_RECORD : string status "success|timeout|infeasible"
    USAGE_RECORD : datetime created_at "indexed"
    
    ANALYTICS_EVENT : string id (pk) "ae_*"
    ANALYTICS_EVENT : string user_id (fk)
    ANALYTICS_EVENT : string organization_id (fk)
    ANALYTICS_EVENT : string event_type "signup|solve_executed|template_purchased|..."
    ANALYTICS_EVENT : string country_code "geo IP"
    ANALYTICS_EVENT : json event_metadata "JSON payload"
    ANALYTICS_EVENT : datetime created_at "indexed"
    
    PLATFORM_SETTING : string key (pk) "solve_maintenance_gate|max_daily_solves|..."
    PLATFORM_SETTING : string value "JSON string"
    PLATFORM_SETTING : datetime updated_at
    PLATFORM_SETTING : string updated_by "nullable"
    
    PLATFORM_SETTING_AUDIT : string id (pk)
    PLATFORM_SETTING_AUDIT : string key (fk)
    PLATFORM_SETTING_AUDIT : string old_value
    PLATFORM_SETTING_AUDIT : string new_value
    PLATFORM_SETTING_AUDIT : string changed_by "nullable"
    PLATFORM_SETTING_AUDIT : datetime changed_at
```

## Critical points

- **PlatformSetting**: global singletons (not org-scoped). E.g.: `solve_maintenance_gate=true` takes all solves offline.
- **PlatformSettingAudit**: full change history. Immutable trail for compliance + rollback.
- **AuditLog**: workspace-scoped. Records per-user actions: create model, share trigger, etc. GDPR retention.
- **Notification + NotificationPreference**: user-scoped. Types: low_credits, execution_complete, payment_received.
- **AnalyticsEvent**: org-scoped + user-scoped. Geolocation (country_code via IP). For seller/admin reports.
- **UsageRecord**: aggregation of executions for usage dashboards. Periodic snapshot (not real-time).

## Relevant files

- `app/models/platform_setting.py:PlatformSetting`
- `app/models/platform_setting_audit.py:PlatformSettingAudit`
- `app/models/audit_log.py:AuditLog, AuditAction`
- `app/models/notification.py:Notification, NotificationType, NotificationChannel`
- `app/models/notification_preference.py:NotificationPreference`
- `app/models/usage_record.py:UsageRecord`
- `app/models/analytics_event.py:AnalyticsEvent`
- `app/services/platform_settings_service.py:PlatformSettingsService` — read cache + write audit
- `app/services/audit_service.py:log_action()` — wrapper for AuditLog creation
- `app/api/v2/routes/admin/` — admin endpoints for settings/audit
