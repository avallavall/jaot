# Use Case: Automation via Triggers — Schedule + Webhook

> Automation flow: cron or inbound HTTP trigger → launches async solve → notifies the result.

## Diagram

```mermaid
sequenceDiagram
    participant User as User
    participant Frontend as Frontend (/triggers)
    participant API as POST /api/v2/triggers
    participant DB as PostgreSQL
    participant CeleryBeat as Celery Beat (scheduler)
    participant RabbitMQ as Celery Queue
    participant Worker as Celery Worker
    participant WebhookOut as Outbound Webhook
    participant Email as Email Service
    
    note over User,API: --- SETUP TRIGGER ---
    User->>Frontend: "Create trigger for model version X"
    Frontend->>API: POST /triggers {document_id, version_id, name, webhook_url, override_schema}
    API->>DB: CREATE SolveTrigger(id='trig_...', document_id, version_id, webhook_url, trigger_secret=hash)
    API->>DB: CREATE TriggerSchedule(trigger_id, cron_expression='0 9 * * MON', is_enabled=true)
    DB-->>API: {trigger_id, trigger_secret_plaintext (only shown once)}
    API->>Frontend: 201 {trigger_id, trigger_secret}
    Frontend->>Frontend: Display instruction: "Keep secret safe for /fire endpoint"
    
    note over CeleryBeat,Worker: --- SCHEDULE FIRING (CRON) ---
    CeleryBeat->>DB: SELECT * FROM trigger_schedules WHERE is_enabled AND cron_matches(now)
    DB-->>CeleryBeat: [{trigger_id='trig_...', cron='0 9 * * MON'}]
    CeleryBeat->>DB: SELECT * FROM solve_triggers WHERE id=trigger_id
    DB-->>CeleryBeat: SolveTrigger + version_id pinned
    
    CeleryBeat->>RabbitMQ: apply_async(queue=resolve_queue(solver), task=solve_model_async, args={trigger_id, override_inputs})
    RabbitMQ-->>CeleryBeat: task_id enqueued
    
    RabbitMQ->>Worker: Dequeue task
    Worker->>DB: SELECT * FROM solve_triggers WHERE id=trigger_id
    DB-->>Worker: SolveTrigger + version_id
    Worker->>Worker: Load model_json from ModelVersion (pinned)
    Worker->>Worker: Apply override_schema inputs (if applicable)
    Worker->>Worker: validate_problem() + compute_credits()
    
    Worker->>DB: Deduct credits: CreditTransaction(type=EXECUTION, org_id)
    Worker->>DB: CREATE ModelExecution(status='pending', trigger_id, ...)
    Worker->>RabbitMQ: apply_async(queue=resolve_queue(solver_name), task=solve_)
    
    Worker->>Worker: Run solve (same pattern as manual solve)
    Worker->>DB: UPDATE ModelExecution(status='completed', result_data, objective_value)
    
    Worker->>WebhookOut: POST {webhook_url} {trigger_secret signature, execution_id, result, objective_value}
    WebhookOut-->>Worker: 200 (e.g. the webhook is an N8N flow or Zapier)
    
    alt Webhook fails (5xx)
        Worker->>Worker: Retry 3x with exponential backoff
        Worker->>Email: send_alert(trigger_owner, "Webhook failed after 3 retries")
    end
    
    Worker->>Email: send_execution_notification(trigger_owner, result_summary)
    Email-->>User: "Trigger executed. Objective: 42.5"
    
    note over User,API: --- MANUAL FIRE (HTTP INBOUND) ---
    
    User->>API: POST /triggers/{trigger_id}/fire {Authorization: Bearer {trigger_secret}}
    API->>API: verify_trigger_secret(trigger_id, header_secret)
    alt Secret invalid
        API->>User: 401 "Unauthorized"
    end
    
    API->>DB: SELECT * FROM solve_triggers WHERE id=trigger_id
    DB-->>API: SolveTrigger
    API->>API: Apply request override_schema (mapping of user inputs → model inputs)
    API->>RabbitMQ: apply_async(solve_model_async, args={trigger_id, user_inputs})
    API->>DB: CREATE TriggerRun(trigger_id, status='pending')
    API->>User: 202 {task_id, status='pending'}
    
    User->>User: Poll GET /triggers/{trigger_id}/runs/{run_id}
    User->>API: GET /triggers/{trigger_id}/runs/{run_id}
    API->>DB: SELECT * FROM trigger_runs WHERE id=run_id AND trigger_id=?
    DB-->>API: {status='completed', execution_id}
    API->>DB: SELECT * FROM model_executions WHERE id=execution_id
    DB-->>API: {objective_value, result_data}
    API->>User: 200 {status, result}
```

## Critical Points

### Schedule (Cron)
1. **Celery Beat**: daemon that reads the `trigger_schedules` table every minute
2. **Cron expression**: standard (0 9 * * MON = 9 AM Mondays)
3. **Timezone**: always UTC (configurable via PSS)
4. **Last run tracking**: `last_run_at` to prevent duplicates if Beat restarts

### Manual Fire (/fire)
1. **Public endpoint**: does not require API key auth (separate trigger secret)
2. **Secret verification**: SHA-256 hash vs header `Authorization: Bearer {secret}`
3. **Rate limiting**: `trigger_id` → max 10/min (configurable)
4. **Override schema**: simplified input mapping (e.g. {qty: 100} → {num_items: 100})

### Webhook Outbound
1. **Signing**: HMAC-SHA256(webhook_secret, payload) in the `X-Trigger-Signature` header
2. **Retry**: 3x with backoff (1s, 2s, 4s)
3. **Timeout**: 30s per attempt
4. **Destination**: any URL (N8N, Zapier, custom endpoint)

### Credits
- **Pre-deduct**: same pattern as manual solve
- **Refund on failure**: if the execution fails, automatic refund
- **Rate limiting**: the `daily_solves` limit still applies

## Relevant Files

- `app/api/v2/triggers.py:POST /triggers/fire` — manual fire endpoint
- `app/models/trigger.py:SolveTrigger, TriggerRun, TriggerSchedule`
- `app/tasks/trigger_tasks.py` — Celery beat task definition
- `app/services/trigger_service.py` — business logic (fire, validate, etc.)
- `app/shared/core/celery_app.py` — Celery config + Beat schedule (`beat_schedule` dict)
- `app/core/prometheus_metrics.py` — trigger execution counters
