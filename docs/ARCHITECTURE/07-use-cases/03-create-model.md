# Use Case: Create Optimization Model — Builder + LLM

> Creation flow: user sketches a model on the canvas, the LLM generates the formulation, saved as ModelBuilderDocument + ModelVersion.

## Diagram

```mermaid
sequenceDiagram
    participant User as User
    participant Frontend as Frontend (/builder)
    participant Canvas as Visual Canvas Component
    participant API as POST /api/v2/llm/messages (stream)
    participant LLM as LLMService (Claude)
    participant RAG as Qdrant (Vector DB)
    participant DB as PostgreSQL
    participant Orch as SolveOrchestrator
    
    User->>Canvas: Sketch variables, constraints, objective
    Canvas->>Canvas: Build canvas_json (tree of nodes)
    
    User->>Frontend: "Generate formulation"
    Frontend->>API: POST /llm/conversations {template_id or model_id?}
    API->>DB: CREATE LLMConversation(org_id, user_id, expires_at=now+24h)
    DB-->>API: conversation_id
    API->>Frontend: 201 {conversation_id}
    
    Frontend->>API: POST /llm/conversations/{id}/messages {content: "...problem description..."}
    API->>API: moderate_message(content) → spam/toxicity check
    API->>API: generate_formulation_resilient(conversation, problem_sketch)
    
    note over LLM,RAG: RAG Pipeline
    LLM->>RAG: embed_query("...problem...")
    RAG-->>LLM: top-k similar templates {model_json, metadata}
    
    LLM->>API: stream_response(sse)
    API->>Frontend: SSE chunks {delta: "min x + y"}
    Frontend->>Canvas: Append chunks to suggestion panel
    
    alt User accepts
        Frontend->>API: POST /models {name, description, canvas_json, model_json}
        API->>Orch: validate_problem(model_json)
        Orch-->>API: valid
        API->>DB: CREATE ModelBuilderDocument(id='doc_...', org_id, name, canvas_json, model_json)
        DB-->>API: document_id
    else User edits
        Canvas->>Canvas: Edit canvas_json manually
        Frontend->>API: POST /builder-documents/{id}/versions {canvas_json, model_json}
    end
    
    API->>DB: CREATE ModelVersion(document_id, canvas_json, model_json, sequence=1, is_named=false)
    DB-->>API: version_id
    
    API->>DB: INSERT LLMMessage(conversation_id, role='assistant', content=full_formulation)
    API->>Frontend: 201 {document_id, version_id, model_status='draft'}
    
    Frontend->>Frontend: Auto-save every 2s: PATCH /builder-documents/{id}
    Frontend->>Frontend: Display validation errors in real time
    
    User->>Frontend: Click "Save as Version"
    Frontend->>API: POST /models/{doc_id}/versions {version_name='v1.0_optimized'}
    API->>DB: CREATE ModelVersion(..., is_named=true, version_name='v1.0_optimized')
    DB-->>API: version_id
    API->>API: log_action(AuditAction.CREATE_VERSION, ...) → AuditLog
    API->>Frontend: 201 {version_id}
    
    alt User publishes model
        Frontend->>API: POST /models/{doc_id}/publish {name, category, price_eur=0}
        API->>DB: CREATE ModelCatalog(name, category, is_published=true, created_by_org_id)
        API->>DB: CREATE ModelVersion (snapshot of published)
        API->>Frontend: 201 {catalog_id, url_to_marketplace}
    end
```

## Critical Points

### Builder Document Lifecycle
1. **Draft**: document created, canvas_json mutable, no ModelVersion yet
2. **Version**: user clicks "Save as Version" → ModelVersion snapshot (immutable)
3. **Published**: sent to ModelCatalog (global), formula locked

### LLM RAG
- **Query embedding**: problem sketch → vector via local `sentence-transformers` (`BAAI/bge-small-en-v1.5`, CPU, 384 dims)
- **Top-k retrieval**: searches Qdrant for similar templates (formulation examples)
- **Prompt engineering**: combines retrieved examples + user sketch → full formulation
- **Streaming**: chunks returned via SSE, frontend renders in real time

### Validation
- **Real-time**: canvas_json is validated against variable refs (constraint refs to vars that don't exist)
- **Pre-save**: model_json passed to SolveOrchestrator.validate_problem()
- **Pre-publish**: full execution test on SCIP/HiGHS mock

### Auto-save
- Frontend auto-saves every 2s: PATCH /builder-documents/{doc_id}
- Server only updates canvas_json, does not create a version
- LLM conversation expires in 24h (configurable)

## Relevant Files

- `app/api/v2/builder.py` — CRUD endpoints for documents
- `app/api/v2/llm.py:POST /llm/conversations/{id}/messages` — stream endpoint
- `app/api/v2/versions.py` — versioning endpoints
- `app/models/builder_document.py:ModelBuilderDocument`
- `app/models/model_version.py:ModelVersion`
- `app/models/optimization_model.py:ModelCatalog`
- `app/services/llm/formulation_service.py:generate_formulation_resilient()`
- `app/services/llm/prompt_templates.py` — RAG + LLM prompts
- `app/services/solve_orchestrator.py:validate_problem()`
