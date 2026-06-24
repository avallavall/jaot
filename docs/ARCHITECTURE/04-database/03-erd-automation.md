# ERD Automation + AI — Triggers, LLM, Builder

> Automation entities: SolveTrigger, TriggerRun, TriggerSchedule, LLMConversation, ModelBuilderDocument, ModelVersion.

## Diagram

```mermaid
erDiagram
    ORGANIZATION ||--o{ SOLVE_TRIGGER : "owns_triggers"
    ORGANIZATION ||--o{ LLM_CONVERSATION : "has_conversations"
    ORGANIZATION ||--o{ MODEL_BUILDER_DOCUMENT : "owns_documents"
    
    WORKSPACE ||--o{ SOLVE_TRIGGER : "scopes_trigger"
    
    USER ||--o{ LLM_CONVERSATION : "starts_conversations"
    USER ||--o{ SOLVE_TRIGGER : "creates_trigger"
    
    SOLVE_TRIGGER ||--o{ TRIGGER_RUN : "fires_runs"
    SOLVE_TRIGGER ||--o{ TRIGGER_SCHEDULE : "has_cron"
    
    MODEL_BUILDER_DOCUMENT ||--o{ MODEL_VERSION : "snapshots"
    MODEL_BUILDER_DOCUMENT ||--o{ SOLVE_TRIGGER : "attached_to"
    
    LLM_CONVERSATION ||--o{ LLM_MESSAGE : "contains_messages"
    LLM_CONVERSATION ||--o{ CONVERSATION_ATTACHMENT : "has_attachments"
    
    ORGANIZATION : string id (pk)
    ORGANIZATION : string name
    
    WORKSPACE : string id (pk)
    WORKSPACE : string organization_id (fk)
    WORKSPACE : string name
    
    USER : string id (pk)
    USER : string email
    USER : string organization_id (fk)
    
    MODEL_BUILDER_DOCUMENT : string id (pk) "doc_*"
    MODEL_BUILDER_DOCUMENT : string organization_id (fk)
    MODEL_BUILDER_DOCUMENT : string name
    MODEL_BUILDER_DOCUMENT : json canvas_json "UI visual tree"
    MODEL_BUILDER_DOCUMENT : json model_json "serialized model"
    MODEL_BUILDER_DOCUMENT : datetime created_at
    
    MODEL_VERSION : string id (pk)
    MODEL_VERSION : string document_id (fk)
    MODEL_VERSION : json canvas_json "snapshot at version time"
    MODEL_VERSION : json model_json "snapshot at version time"
    MODEL_VERSION : int sequence "auto-incrementing"
    MODEL_VERSION : bool is_named "user gave it a name"
    MODEL_VERSION : string version_name "nullable"
    
    SOLVE_TRIGGER : string id (pk) "trig_*"
    SOLVE_TRIGGER : string organization_id (fk)
    SOLVE_TRIGGER : string document_id (fk)
    SOLVE_TRIGGER : string version_id (fk) "RESTRICT: version pinned"
    SOLVE_TRIGGER : string workspace_id "nullable"
    SOLVE_TRIGGER : string created_by (fk to User)
    SOLVE_TRIGGER : string name
    SOLVE_TRIGGER : string description "nullable"
    SOLVE_TRIGGER : string trigger_secret "SHA-256 hash"
    SOLVE_TRIGGER : string webhook_url
    SOLVE_TRIGGER : string webhook_secret "nullable"
    SOLVE_TRIGGER : json override_schema "input field mapping"
    SOLVE_TRIGGER : bool is_enabled
    SOLVE_TRIGGER : int total_runs "counter"
    
    TRIGGER_RUN : string id (pk)
    TRIGGER_RUN : string trigger_id (fk)
    TRIGGER_RUN : string execution_id (fk) "FK to ModelExecution"
    TRIGGER_RUN : string status "pending|executing|completed|failed"
    TRIGGER_RUN : datetime started_at
    TRIGGER_RUN : datetime finished_at
    
    TRIGGER_SCHEDULE : string id (pk) "sched_*"
    TRIGGER_SCHEDULE : string trigger_id (fk)
    TRIGGER_SCHEDULE : string cron_expression "0 9 * * MON"
    TRIGGER_SCHEDULE : bool is_enabled
    TRIGGER_SCHEDULE : datetime last_run_at "nullable"
    
    LLM_CONVERSATION : string id (pk) "conv_*"
    LLM_CONVERSATION : string organization_id (fk)
    LLM_CONVERSATION : string user_id (fk)
    LLM_CONVERSATION : string model_id "FK to ModelBuilderDocument, nullable"
    LLM_CONVERSATION : datetime expires_at "TTL: 24h default"
    LLM_CONVERSATION : datetime created_at
    
    LLM_MESSAGE : string id (pk)
    LLM_MESSAGE : string conversation_id (fk)
    LLM_MESSAGE : string role "user|assistant"
    LLM_MESSAGE : string content
    LLM_MESSAGE : datetime created_at
    
    CONVERSATION_ATTACHMENT : string id (pk)
    CONVERSATION_ATTACHMENT : string conversation_id (fk)
    CONVERSATION_ATTACHMENT : string filename
    CONVERSATION_ATTACHMENT : string content_text "extracted text"
    CONVERSATION_ATTACHMENT : datetime created_at
```

## Critical points

- **ModelBuilderDocument + ModelVersion**: the document is mutable, versions are immutable snapshots. Every push to versionHistory creates a ModelVersion.
- **SolveTrigger.version_id**: FK with RESTRICT. A version cannot be deleted while it is pinned to an active trigger.
- **TriggerSchedule**: 1:1 with SolveTrigger. Celery Beat reads this table every minute and dispatches async tasks.
- **LLMConversation**: org-scoped + user-scoped. Expires automatically after 24h (configurable via PSS).
- **ConversationAttachment**: extracted from PDFs/docx via `document_extraction.py`, indexed for RAG.

## Relevant files

- `app/models/builder_document.py:ModelBuilderDocument`
- `app/models/model_version.py:ModelVersion`
- `app/models/trigger.py:SolveTrigger, TriggerRun, TriggerSchedule`
- `app/models/llm_conversation.py:LLMConversation, LLMMessage`
- `app/models/conversation_attachment.py:ConversationAttachment`
- `app/api/v2/triggers.py` — CRUD + /fire endpoint
- `app/api/v2/llm.py` — conversation management + streaming
- `app/services/llm/formulation_service.py` — RAG + Claude
