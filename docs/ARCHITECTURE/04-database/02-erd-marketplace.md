# ERD Marketplace — Listings + Reviews + Favorites

> Marketplace entities post-fusion (ADR-006 / P1.5): the marketplace is a **facet** of the
> studio's `ModelProject` — a 1:1 `ModelProjectListing` row. Favorites, view events and
> reviews all key on `model_project_id`.

> **Note (ADR-008, 2026-07-10):** the marketplace is **free and collaborative** — the monetized
> entities that used to appear here (`price_eur`, `stripe_connect_*`, `FeaturedPlacement`,
> `SellerToSAcceptance`) were removed from the application.

> **Note (P1.5 fusion, 2026-07-13):** the legacy tables `model_catalog` and
> `organization_models` (plus the legacy FK columns `model_reviews.catalog_id`,
> `user_favorites.model_id`, `recent_models.model_id`, `model_view_events.catalog_model_id`)
> are **dead but still present** in the schema (kept for one release). A later contract
> release drops them.

## Diagram

```mermaid
erDiagram
    ORGANIZATION ||--o{ MODEL_PROJECT : "owns"
    ORGANIZATION ||--o{ VERIFICATION_REQUEST : "requests_badge"

    MODEL_PROJECT ||--|| MODEL_PROJECT_LISTING : "publishes_as (1:1 facet)"
    MODEL_PROJECT ||--o{ MODEL_PROJECT_VERSION : "commits"

    USER ||--o{ USER_FAVORITE : "favorites_models"
    USER ||--o{ FORMULATION_RATING : "rates_formulations"
    USER ||--o{ MODEL_REVIEW : "reviews_models"

    MODEL_PROJECT ||--o{ USER_FAVORITE : "favorited_by"
    MODEL_PROJECT ||--o{ MODEL_VIEW_EVENT : "gets_viewed"
    MODEL_PROJECT ||--o{ MODEL_REVIEW : "receives_reviews"

    LLM_CONVERSATION ||--o{ FORMULATION_RATING : "triggers_feedback"

    ORGANIZATION : string id (pk)
    ORGANIZATION : string name
    ORGANIZATION : bool is_verified "author badge"

    USER : string id (pk)
    USER : string email
    USER : string slug "public username"
    USER : string display_name
    USER : string bio "profile"

    MODEL_PROJECT : string id (pk) "mp_* (or preserved legacy id)"
    MODEL_PROJECT : string organization_id (fk) "author org"
    MODEL_PROJECT : string source_type "builder|template|marketplace|import|..."
    MODEL_PROJECT : string source_ref "origin listing/template id (forks)"
    MODEL_PROJECT : string current_version_id "last commit"

    MODEL_PROJECT_LISTING : string model_project_id (pk/fk) "1:1 with the project"
    MODEL_PROJECT_LISTING : string name "public name"
    MODEL_PROJECT_LISTING : string category "finance|logistics|..."
    MODEL_PROJECT_LISTING : string status "draft|published"
    MODEL_PROJECT_LISTING : bool is_public
    MODEL_PROJECT_LISTING : bool is_official "seeded from the template library"
    MODEL_PROJECT_LISTING : string pinned_version_id "the version the marketplace serves"
    MODEL_PROJECT_LISTING : string author_organization_id (fk)
    MODEL_PROJECT_LISTING : string generator_type "nullable — generator facet (officials)"
    MODEL_PROJECT_LISTING : json input_schema "nullable"
    MODEL_PROJECT_LISTING : int total_activations "adoptions (forks)"
    MODEL_PROJECT_LISTING : int total_executions
    MODEL_PROJECT_LISTING : float avg_rating "auto-computed rollup"
    MODEL_PROJECT_LISTING : int view_count

    USER_FAVORITE : string id (pk)
    USER_FAVORITE : string user_id (fk)
    USER_FAVORITE : string model_project_id (fk)
    USER_FAVORITE : datetime created_at

    MODEL_VIEW_EVENT : string id (pk)
    MODEL_VIEW_EVENT : string model_project_id (fk)
    MODEL_VIEW_EVENT : string event_type "impression|view|download"
    MODEL_VIEW_EVENT : string user_id "nullable (anonymous)"
    MODEL_VIEW_EVENT : string country_code

    MODEL_REVIEW : string id (pk)
    MODEL_REVIEW : string model_project_id (fk)
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
    LLM_CONVERSATION : string model_project_id "nullable — studio-scoped chats"
```

## Critical points

- **ModelProjectListing**: the ONLY marketplace entity. PK == FK to `model_projects`
  (CASCADE). The project stays org-scoped and editable; the listing serves the **pinned
  committed version** publicly. Officials (the 102 template seeds) carry a *generator facet*
  (`generator_type` + `input_schema`); community listings are static snapshots.
- **Adoption, not sales**: "Use in studio" forks the listing into the adopter's org
  (`ModelProject.source_type='marketplace'`, `source_ref=listing id`) and bumps
  `total_activations` atomically.
- **Reviews**: keyed on `model_project_id`, gated anti-spam (reviewer's org must have a fork
  + a completed execution); `avg_rating` rolls up onto the listing.
- **Ratings** (formulation): tied to LLM conversations, not executions. Feedback on
  formulation quality.
- **Verification**: badge only for verified authors (anti-spam).

## Relevant files

- `app/models/model_project.py:ModelProject, ModelProjectVersion, ModelProjectListing`
- `app/models/favorite.py:UserFavorite` — user bookmarks
- `app/models/formulation_rating.py:FormulationRating` — LLM feedback
- `app/models/verification_request.py:VerificationRequest` — author verification
- `app/models/model_view_event.py:ModelViewEvent` — analytics
- `app/api/v2/routes/models/catalog.py` — public browse/detail/schema over listings
