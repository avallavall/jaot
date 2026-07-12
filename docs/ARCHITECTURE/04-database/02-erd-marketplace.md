# ERD Marketplace — Community + Catalog + Reviews

> Marketplace entities: ModelCatalog (global), Favorites, FormulationRatings, Verification, ViewEvents.

> **Note (ADR-008, 2026-07-10):** the marketplace is **free and collaborative** — the monetized
> entities that used to appear here (`price_eur`, `stripe_connect_*`, `FeaturedPlacement`,
> `SellerToSAcceptance`) were removed from the application. Their tables/columns stay in the
> schema (additive-only, dead and unmapped) until a later release drops them.

## Diagram

```mermaid
erDiagram
    ORGANIZATION ||--o{ VERIFICATION_REQUEST : "requests_badge"
    ORGANIZATION ||--o{ SELLER_TOS_ACCEPTANCE : "accepts_tos"
    
    USER ||--o{ USER_FAVORITE : "favorites_models"
    USER ||--o{ FORMULATION_RATING : "rates_formulations"
    USER ||--o{ MODEL_REVIEW : "reviews_models"
    
    MODEL_CATALOG ||--o{ USER_FAVORITE : "favorited_by"
    MODEL_CATALOG ||--o{ MODEL_VIEW_EVENT : "gets_viewed"
    MODEL_CATALOG ||--o{ MODEL_REVIEW : "receives_reviews"
    
    LLM_CONVERSATION ||--o{ FORMULATION_RATING : "triggers_feedback"
    
    ORGANIZATION : string id (pk)
    ORGANIZATION : string name
    ORGANIZATION : bool is_verified "seller badge"
    
    USER : string id (pk)
    USER : string email
    USER : string slug "public username"
    USER : string display_name
    USER : string bio "profile"
    
    MODEL_CATALOG : string id (pk) "model_*"
    MODEL_CATALOG : string name "public name"
    MODEL_CATALOG : string category "finance|logistics|..."
    MODEL_CATALOG : float price_eur "marketplace price"
    MODEL_CATALOG : bool is_published
    MODEL_CATALOG : string created_by_org_id "FK to Organization"
    MODEL_CATALOG : int view_count
    MODEL_CATALOG : float avg_rating "auto-computed"
    
    USER_FAVORITE : string id (pk)
    USER_FAVORITE : string user_id (fk)
    USER_FAVORITE : string model_id (fk)
    USER_FAVORITE : datetime created_at
    
    MODEL_VIEW_EVENT : string id (pk)
    MODEL_VIEW_EVENT : string model_id (fk)
    MODEL_VIEW_EVENT : string event_type "impression|view|download"
    MODEL_VIEW_EVENT : string user_id "nullable (anonymous)"
    MODEL_VIEW_EVENT : string country_code
    
    MODEL_REVIEW : string id (pk)
    MODEL_REVIEW : string model_id (fk)
    MODEL_REVIEW : string user_id (fk)
    MODEL_REVIEW : int rating "1-5"
    MODEL_REVIEW : string comment "nullable"
    
    FORMULATION_RATING : string id (pk)
    FORMULATION_RATING : string conversation_id (fk)
    FORMULATION_RATING : string zone "objective|constraint_0|..."
    FORMULATION_RATING : string rating "up|down"
    FORMULATION_RATING : string comment "nullable"
    
    VERIFICATION_REQUEST : string id (pk)
    VERIFICATION_REQUEST : string organization_id (fk)
    VERIFICATION_REQUEST : string status "pending|approved|rejected"
    VERIFICATION_REQUEST : datetime created_at
    
    LLM_CONVERSATION : string id (pk)
    LLM_CONVERSATION : string organization_id (fk)
    LLM_CONVERSATION : string model_id "FK to ModelBuilderDocument"
```

## Critical points

- **ModelCatalog**: global entity (not org-scoped). `author_organization_id` references the publisher.
- **Ratings**: tied to LLM conversations, not to executions. Feedback on formulation quality.
- **Verification**: badge only for verified publishers (anti-spam).

## Relevant files

- `app/models/optimization_model.py:ModelCatalog` — the global catalog
- `app/models/favorite.py:UserFavorite` — user bookmarks
- `app/models/formulation_rating.py:FormulationRating` — LLM feedback
- `app/models/verification_request.py:VerificationRequest` — publisher verification
- `app/models/seller_tos_acceptance.py:SellerTosAcceptance` — compliance
- `app/models/model_view_event.py:ModelViewEvent` — analytics (phase 79)
