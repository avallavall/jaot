# Use Case: Marketplace Activation — Model Acquisition

> Acquisition flow: user browses the catalog, previews a model, activates it for free, and solves with it.

> **Note (ADR-008, 2026-07-10):** the marketplace is **free and collaborative**. The former paid
> purchase flow (Stripe checkout, commission split, seller payouts, credit ledger) was removed
> entirely — activation costs nothing, always. This document describes the current flow.

## Diagram

```mermaid
sequenceDiagram
    participant User as User
    participant Frontend as Frontend (/marketplace)
    participant API as API v2
    participant DB as PostgreSQL

    User->>Frontend: Search models by category
    Frontend->>API: GET /models/catalog?category=logistics
    API->>DB: SELECT * FROM model_catalog WHERE category='logistics' AND status='published'
    DB-->>API: [{id, name, avg_rating, view_count}, ...]
    API->>Frontend: 200 [models]

    Frontend->>Frontend: Display cards (name, category, reviews, rating)
    User->>Frontend: Click "Preview" on a model
    Frontend->>API: GET /models/catalog/{model_id}
    API->>DB: SELECT * FROM model_catalog WHERE id=?
    DB-->>API: {name, description, category, review_count}
    API->>DB: INSERT ModelViewEvent(model_id, event_type='view', viewer_org, country)

    API->>Frontend: 200 {model}
    Frontend->>Frontend: Display preview (read-only), reviews, rating, author info

    User->>Frontend: Click "Activate model"
    Frontend->>API: POST /models/catalog/{model_id}/activate
    API->>DB: SELECT OrganizationModel WHERE org_id=? AND catalog_id=?
    alt Already activated
        API->>Frontend: 400 "Model already activated"
    end
    API->>DB: CREATE OrganizationModel(org_id, catalog_id, is_active=true)
    API->>DB: INSERT AuditLog(actor_id, action='activate_model', target_type='model_catalog', ...)
    API->>Frontend: 200 {message, model_id}
    Frontend->>Frontend: Redirect to /solve with the model available

    User->>Frontend: Solve with the activated model
    Frontend->>API: POST /models/{model_id}/execute {input_data}
    API->>DB: SELECT * FROM organization_models WHERE id=? AND organization_id=?
    DB-->>API: model (accessible)
    API->>API: async solve pipeline (ADR-007) → normal execution
```

There is also a second, newer acquisition path: **"Use in studio"** materializes the catalog model
into a first-class `ModelProject` (editable + versioned) via `POST /projects/from-marketplace/{id}`,
instead of activating it as a parametric `OrganizationModel`.

## Critical Points

### No payment layer
- Activation is free by design (ADR-008); there is no price, no commission, no ledger entry.
- Fair use is enforced elsewhere: rate limits, daily solve quota, per-solve time/size caps.

### Access Control
- **OrganizationModel**: join table that explicitly grants access to the activating org
- **Without access**: the query fails `WHERE organization_id=? AND model_id=?` → 404
- **Solve execution**: always filtered by org_id

### Analytics (non-monetary)
- **ModelViewEvent**: records impressions + views per model
- **Seller analytics**: views, impressions, activations of your published models
  (`SellerAnalyticsService`; a foreign org activating its own model never counts for you)
- **Ratings**: ModelReview (measures model quality, drives catalog `min_rating` filter)

## Relevant Files

- `app/api/v2/routes/models/catalog.py:POST /models/catalog/{model_id}/activate` — activation
- `app/api/v2/projects.py:POST /projects/from-marketplace/{id}` — materialize into the studio
- `app/services/seller_analytics_service.py` — non-monetary seller analytics
- `app/models/optimization_model.py:ModelCatalog, OrganizationModel`
- `app/models/model_view_event.py:ModelViewEvent` — analytics
