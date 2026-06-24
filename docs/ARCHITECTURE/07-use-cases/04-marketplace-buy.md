# Use Case: Marketplace Purchase — Template Acquisition

> Purchase flow: user browses templates, previews, pays via Stripe, access granted, forks to own model.

## Diagram

```mermaid
sequenceDiagram
    participant User as Buyer
    participant Frontend as Frontend (/marketplace)
    participant Browse as Browse Templates
    participant API as POST /api/v2/seller/checkout
    participant DB as PostgreSQL
    participant Stripe as Stripe Payments
    participant Email as Email Service
    
    User->>Browse: Search templates by category
    Browse->>API: GET /marketplace/models?category=logistics&sort=price
    API->>DB: SELECT * FROM model_catalog WHERE category='logistics' AND is_published
    DB-->>API: [{id, name, price_eur, avg_rating, view_count}, ...]
    API->>Frontend: 200 [models]
    
    Browse->>Browse: Display cards (name, category, reviews, price)
    User->>Browse: Click "Preview" on a model
    Browse->>API: GET /marketplace/models/{model_id}
    API->>DB: SELECT * FROM model_catalog WHERE id=?
    DB-->>API: {name, description, category, price_eur, review_count}
    API->>DB: INSERT ModelViewEvent(model_id, event_type='view', user_id, country_code)
    
    API->>Frontend: 200 {model}
    Frontend->>Frontend: Display preview canvas (read-only)
    Frontend->>Frontend: Display reviews, rating, seller info
    
    User->>Frontend: Click "Purchase for 50 EUR"
    Frontend->>API: POST /seller/checkout {model_id, payment_method='card'}
    
    API->>API: calculate_commission_split(price_eur=50)
    API->>API: {platform_commission=10, seller_earnings=40} ← 20% platform fee
    
    API->>Stripe: create_checkout_session {
        line_items=[{name, amount_eur=50, currency='eur'}],
        customer_id,
        success_url, cancel_url
    }
    Stripe-->>API: {checkout_session_id, url}
    API->>Frontend: 201 {checkout_url}
    
    Frontend->>Frontend: Redirect to Stripe checkout
    User->>Stripe: Enter card (Stripe hosted)
    Stripe-->>User: "Payment successful"
    Stripe->>API: webhook POST /webhooks/stripe {event='charge.succeeded', charge_id}
    
    API->>DB: SELECT CreditTransaction WHERE reference_type='stripe_charge' AND reference_id=charge_id
    alt Already processed
        API->>API: idempotent (no double-credit)
    end
    
    API->>DB: INSERT CreditTransaction(org_id=seller_org, type=SALE_EARNING, credits_amount=40)
    API->>DB: UPDATE organization SET credits_earned += 40
    API->>DB: INSERT CreditTransaction(org_id=platform, type=COMMISSION, amount_eur=10)
    
    API->>DB: CREATE OrganizationModel(buyer_org_id, catalog_id=model_id, custom_name=?, is_active=true)
    API->>DB: INSERT AuditLog(actor_id, action='purchase_template', target_type='model_catalog', ...)
    
    API->>Email: send_purchase_confirmation(buyer_email, seller_email)
    Email-->>User: "Template purchased! You now have access."
    Email-->>Seller: "Your template was purchased. +40 credits earned."
    
    API->>Frontend: 200 {message: "Model added to your account", model_id}
    Frontend->>Frontend: Redirect to /solver with the model loaded
    
    User->>Frontend: Click "Solve with this template"
    Frontend->>API: POST /solve {model_id, input_data}
    API->>DB: SELECT * FROM organization_models WHERE id=model_id AND org_id=?
    DB-->>API: model (now accessible)
    API->>API: solve_orchestrator.solve(...) → normal execution
```

## Critical Points

### Payment Model
- **Stripe integration**: `stripe_customer_id` on Organization
- **Commission split**: the platform takes a fixed % (configurable via PSS)
- **Seller earnings**: accumulated in the `credits_earned` pool (withdrawable after the hold period)
- **Platform commission**: stored as CreditTransaction(COMMISSION) for audit

### Idempotency
- Webhook retry (Stripe retries) → UNIQUE constraint on CreditTransaction prevents double-credit:
  - `UNIQUE(organization_id, transaction_type, reference_type, reference_id)`

### Access Control
- **OrganizationModel**: join table that explicitly grants access to the buyer
- **Without access**: the query fails `WHERE organization_id=buyer_org AND model_id=?` → 404
- **Solve execution**: always filtered by org_id

### Analytics
- **ModelViewEvent**: records impressions + views per user
- **FeaturedPlacement**: premium boost (purchased homepage spots)
- **Ratings**: FormulationRating (separate from purchase, measures formulation quality)

## Relevant Files

- `app/api/v2/seller.py:POST /seller/checkout` — create Stripe session
- `app/api/v2/community.py` or `marketplace.py` — browse templates
- `app/services/stripe_connect_service.py` — webhook handler + payout logic
- `app/models/optimization_model.py:ModelCatalog, OrganizationModel`
- `app/models/model_view_event.py:ModelViewEvent` — analytics
- `app/models/credit_transaction.py:CreditTransaction` — ledger entry
- `app/models/invoice.py:Invoice` — optional invoice generation
- `app/api/v2/billing.py:POST /billing/webhook` — Stripe webhook endpoint handler
