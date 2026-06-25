"""
Billing endpoints — Stripe checkout, subscriptions, webhooks, and invoices.

All endpoints require authentication except the webhook endpoint.
"""

import logging
from typing import Any

try:
    import stripe

    StripeError = stripe.StripeError
except (ImportError, AttributeError):
    StripeError = Exception  # type: ignore[assignment,misc]
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_monetization_enabled
from app.api.v2.auth import get_current_user
from app.models import Organization, User
from app.services.invoice_service import InvoiceService
from app.services.stripe_service import StripeService
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


class CreateCheckoutRequest(BaseModel):
    plan: str = Field(..., description="Plan name: starter, pro, business")
    success_url: str = Field(
        default="http://localhost:3000/workspace/credits?checkout=success",
        description="URL to redirect after successful payment",
    )
    cancel_url: str = Field(
        default="http://localhost:3000/workspace/credits?checkout=cancelled",
        description="URL to redirect if user cancels",
    )


class CreateTopupRequest(BaseModel):
    credits: int = Field(
        ...,
        gt=0,
        description="Credits to purchase: 500, 2000, 5000, 20000",
    )
    success_url: str = Field(
        default="http://localhost:3000/workspace/credits?topup=success",
    )
    cancel_url: str = Field(
        default="http://localhost:3000/workspace/credits?topup=cancelled",
    )


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class SubscriptionResponse(BaseModel):
    id: str | None = None
    status: str | None = None
    plan: str | None = None
    current_period_start: str | None = None
    current_period_end: str | None = None
    cancel_at_period_end: bool | None = None


class PortalRequest(BaseModel):
    return_url: str = Field(
        default="http://localhost:3000/workspace/credits",
    )


class PortalResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    stripe_configured: bool
    has_subscription: bool
    subscription: SubscriptionResponse | None = None


def _require_stripe() -> None:
    """Raise 503 if Stripe is not configured."""
    if not StripeService.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured. Set STRIPE_SECRET_KEY in environment.",
        )


@router.get("/status", response_model=BillingStatusResponse)
async def get_billing_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BillingStatusResponse:
    """Get billing status for the current organization."""
    configured = StripeService.is_configured()
    subscription = None
    has_sub = False

    if configured:
        org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
        if org:
            service = StripeService(db)
            sub_data = service.get_subscription(org)
            if sub_data:
                has_sub = True
                subscription = SubscriptionResponse(**sub_data)

    return BillingStatusResponse(
        stripe_configured=configured,
        has_subscription=has_sub,
        subscription=subscription,
    )


@router.post(
    "/checkout/subscription",
    response_model=CheckoutResponse,
    dependencies=[Depends(require_monetization_enabled)],
)
async def create_subscription_checkout(
    body: CreateCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckoutResponse:
    """Create a Stripe Checkout session for a subscription plan."""
    _require_stripe()

    if body.plan.lower() not in ("starter", "pro", "business"):
        raise HTTPException(
            status_code=400,
            detail="Invalid plan. Choose: starter, pro, business",
        )

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = StripeService(db)
    try:
        result = service.create_subscription_checkout(
            organization=org,
            plan=body.plan.lower(),
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
        db.commit()
        return CheckoutResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except StripeError as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(status_code=502, detail="Payment service error") from e


@router.post(
    "/checkout/topup",
    response_model=CheckoutResponse,
    dependencies=[Depends(require_monetization_enabled)],
)
async def create_topup_checkout(
    body: CreateTopupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckoutResponse:
    """Create a Stripe Checkout session for a credit top-up."""
    _require_stripe()

    valid_amounts = [500, 2000, 5000, 20000]
    if body.credits not in valid_amounts:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid credit amount. Choose: {valid_amounts}",
        )

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = StripeService(db)
    try:
        result = service.create_topup_checkout(
            organization=org,
            credits=body.credits,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
        db.commit()
        return CheckoutResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except StripeError as e:
        logger.error(f"Stripe topup checkout error: {e}")
        raise HTTPException(status_code=502, detail="Payment service error") from e


@router.get(
    "/subscription",
    response_model=SubscriptionResponse,
    dependencies=[Depends(require_monetization_enabled)],
)
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """Get current subscription details."""
    _require_stripe()

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = StripeService(db)
    sub = service.get_subscription(org)
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")

    return SubscriptionResponse(**sub)


@router.post("/subscription/cancel", dependencies=[Depends(require_monetization_enabled)])
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Cancel subscription at end of current billing period."""
    _require_stripe()

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = StripeService(db)
    try:
        result = service.cancel_subscription(org)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/portal",
    response_model=PortalResponse,
    dependencies=[Depends(require_monetization_enabled)],
)
async def create_billing_portal(
    body: PortalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortalResponse:
    """Create a Stripe Billing Portal session for self-service management."""
    _require_stripe()

    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = StripeService(db)
    try:
        result = service.create_billing_portal_session(org, body.return_url)
        db.commit()
        return PortalResponse(**result)
    except StripeError as e:
        logger.error(f"Billing portal error: {e}")
        raise HTTPException(status_code=502, detail="Payment service error") from e


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Stripe webhook endpoint.

    This endpoint receives events from Stripe and processes them.
    It must be publicly accessible (no auth middleware).
    Configure the webhook URL in Stripe Dashboard:
        https://your-domain.com/api/v2/billing/webhook
    """
    if not StripeService.is_configured():
        logger.warning("Stripe webhook received but Stripe is not configured")
        raise HTTPException(status_code=400, detail="Stripe is not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    service = StripeService(db)
    try:
        result = service.process_webhook(payload, sig_header)
        db.commit()
        return result
    except ValueError as e:
        logger.warning(f"Webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except StripeError as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed") from e


class InvoiceResponse(BaseModel):
    id: str
    invoice_number: str
    invoice_type: str
    status: str
    issued_at: str
    paid_at: str | None = None
    org_name: str
    subtotal_eur: float
    tax_rate: float
    tax_amount_eur: float
    total_eur: float
    currency: str
    total_local: float
    credits_granted: int
    line_items: list[dict[str, Any]] | None = None
    notes: str | None = None


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvoiceListResponse:
    """List invoices for the current organization."""
    service = InvoiceService(db)
    invoices = service.get_invoices(
        organization_id=current_user.organization_id,
        limit=limit,
        offset=offset,
    )

    items = [
        InvoiceResponse(
            id=inv.id,
            invoice_number=inv.invoice_number,
            invoice_type=inv.invoice_type,
            status=inv.status,
            issued_at=inv.issued_at.isoformat() if inv.issued_at else "",
            paid_at=inv.paid_at.isoformat() if inv.paid_at else None,
            org_name=inv.org_name,
            subtotal_eur=inv.subtotal_eur,
            tax_rate=inv.tax_rate,
            tax_amount_eur=inv.tax_amount_eur,
            total_eur=inv.total_eur,
            currency=inv.currency,
            total_local=inv.total_local,
            credits_granted=inv.credits_granted,
            line_items=inv.line_items,  # type: ignore[arg-type]
            notes=inv.notes,
        )
        for inv in invoices
    ]

    return InvoiceListResponse(items=items, total=len(items))


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvoiceResponse:
    """Get a specific invoice."""
    service = InvoiceService(db)
    invoice = service.get_invoice(invoice_id, current_user.organization_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        invoice_type=invoice.invoice_type,
        status=invoice.status,
        issued_at=invoice.issued_at.isoformat() if invoice.issued_at else "",
        paid_at=invoice.paid_at.isoformat() if invoice.paid_at else None,
        org_name=invoice.org_name,
        subtotal_eur=invoice.subtotal_eur,
        tax_rate=invoice.tax_rate,
        tax_amount_eur=invoice.tax_amount_eur,
        total_eur=invoice.total_eur,
        currency=invoice.currency,
        total_local=invoice.total_local,
        credits_granted=invoice.credits_granted,
        line_items=invoice.line_items,  # type: ignore[arg-type]
        notes=invoice.notes,
    )


@router.get("/invoices/{invoice_id}/html", response_class=HTMLResponse)
async def get_invoice_html(
    invoice_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Get an invoice rendered as printable HTML (use browser Print to save as PDF)."""
    service = InvoiceService(db)
    invoice = service.get_invoice(invoice_id, current_user.organization_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    html = service.render_invoice_html(invoice)
    return HTMLResponse(content=html)
