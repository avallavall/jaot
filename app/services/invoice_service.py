"""
Invoice service for generating and managing invoices.

Generates invoices for:
- Subscription payments (monthly/annual)
- Credit top-up purchases
- Admin adjustments

Invoices are stored in the database and can be rendered as HTML
for PDF conversion (browser print or wkhtmltopdf).
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceStatus, InvoiceType, Organization
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


def _next_invoice_number(db: Session, org_id: str) -> str:
    """Generate the next sequential invoice number using a DB sequence.

    Uses PostgreSQL SEQUENCE for atomic, race-condition-free numbering.
    Format: INV-{YEAR}-{SEQUENCE:05d}
    """
    result = db.execute(text("SELECT nextval('invoice_number_seq')")).scalar()
    year = utcnow().strftime("%Y")
    return f"INV-{year}-{result:05d}"


PLAN_PRICES_EUR = {
    "starter": {"monthly": 19.0, "annual": 190.0, "credits": 600},
    "pro": {"monthly": 49.0, "annual": 490.0, "credits": 2500},
    "business": {"monthly": 149.0, "annual": 1490.0, "credits": 20000},
}

TOPUP_PRICES_EUR = {
    500: 14.0,
    2000: 48.0,
    5000: 100.0,
    20000: 320.0,
}


class InvoiceService:
    """Service for creating and managing invoices."""

    def __init__(self, db: Session):
        self.db = db

    def create_subscription_invoice(
        self,
        organization: Organization,
        plan: str,
        annual: bool = False,
        stripe_invoice_id: str | None = None,
        stripe_payment_intent_id: str | None = None,
    ) -> Invoice:
        """Create an invoice for a subscription payment."""
        pricing = PLAN_PRICES_EUR.get(plan)
        if not pricing:
            raise ValueError(f"Unknown plan: {plan}")

        period = "annual" if annual else "monthly"
        unit_price = pricing[period]
        credits = int(pricing["credits"]) * (12 if annual else 1)

        line_items = [
            {
                "description": f"JAOT {plan.capitalize()} Plan ({period})",
                "quantity": 1,
                "unit_price_eur": unit_price,
                "total_eur": unit_price,
                "credits": credits,
            }
        ]

        return self._create_invoice(
            organization=organization,
            invoice_type=InvoiceType.SUBSCRIPTION,
            line_items=line_items,
            subtotal_eur=unit_price,
            credits_granted=credits,
            stripe_invoice_id=stripe_invoice_id,
            stripe_payment_intent_id=stripe_payment_intent_id,
            notes=f"{plan.capitalize()} plan — {period} billing",
        )

    def create_topup_invoice(
        self,
        organization: Organization,
        credits: int,
        stripe_invoice_id: str | None = None,
        stripe_payment_intent_id: str | None = None,
    ) -> Invoice:
        """Create an invoice for a credit top-up purchase."""
        price = TOPUP_PRICES_EUR.get(credits)
        if price is None:
            raise ValueError(f"Invalid top-up amount: {credits}")

        price_per_credit = price / credits

        line_items = [
            {
                "description": f"Credit Top-Up: {credits:,} credits",
                "quantity": credits,
                "unit_price_eur": round(price_per_credit, 4),
                "total_eur": price,
                "credits": credits,
            }
        ]

        return self._create_invoice(
            organization=organization,
            invoice_type=InvoiceType.TOPUP,
            line_items=line_items,
            subtotal_eur=price,
            credits_granted=credits,
            stripe_invoice_id=stripe_invoice_id,
            stripe_payment_intent_id=stripe_payment_intent_id,
            notes=f"Credit top-up: {credits:,} credits",
        )

    def create_adjustment_invoice(
        self,
        organization: Organization,
        description: str,
        amount_eur: float,
        credits: int,
    ) -> Invoice:
        """Create an invoice for an admin credit adjustment."""
        line_items = [
            {
                "description": description,
                "quantity": 1,
                "unit_price_eur": amount_eur,
                "total_eur": amount_eur,
                "credits": credits,
            }
        ]

        return self._create_invoice(
            organization=organization,
            invoice_type=InvoiceType.ADJUSTMENT,
            line_items=line_items,
            subtotal_eur=amount_eur,
            credits_granted=credits,
            notes=description,
        )

    def _create_invoice(
        self,
        organization: Organization,
        invoice_type: InvoiceType,
        line_items: list[dict[str, Any]],
        subtotal_eur: float,
        credits_granted: int,
        stripe_invoice_id: str | None = None,
        stripe_payment_intent_id: str | None = None,
        notes: str | None = None,
    ) -> Invoice:
        """Internal: create and persist an invoice."""
        tax_rate = 0.0  # No VAT for now (B2B reverse charge / non-EU)
        tax_amount = round(subtotal_eur * tax_rate, 2)
        total_eur = round(subtotal_eur + tax_amount, 2)

        # Currency conversion
        currency = getattr(organization, "currency", "EUR") or "EUR"
        exchange_rate = 1.0  # Simplified; in production, fetch from ExchangeRate table
        total_local = round(total_eur * exchange_rate, 2)

        invoice = Invoice(
            id=f"inv_{uuid.uuid4().hex[:16]}",
            invoice_number=_next_invoice_number(self.db, organization.id),
            organization_id=organization.id,
            invoice_type=invoice_type.value,
            status=InvoiceStatus.PAID.value,
            issued_at=utcnow(),
            paid_at=utcnow(),
            due_at=utcnow() + timedelta(days=30),
            org_name=organization.name,
            org_email=getattr(organization, "billing_email", None),
            org_plan=getattr(organization, "plan", "free"),
            line_items=line_items,
            subtotal_eur=subtotal_eur,
            tax_rate=tax_rate,
            tax_amount_eur=tax_amount,
            total_eur=total_eur,
            currency=currency,
            exchange_rate=exchange_rate,
            total_local=total_local,
            credits_granted=credits_granted,
            stripe_invoice_id=stripe_invoice_id,
            stripe_payment_intent_id=stripe_payment_intent_id,
            notes=notes,
        )

        self.db.add(invoice)
        self.db.flush()
        self.db.refresh(invoice)

        logger.info(
            f"Invoice created: {invoice.invoice_number} for org {organization.id} — €{total_eur}"
        )
        return invoice

    def get_invoices(
        self,
        organization_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Invoice]:
        """Get invoices for an organization."""
        return (
            self.db.query(Invoice)
            .filter(Invoice.organization_id == organization_id)
            .order_by(desc(Invoice.issued_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_invoice(self, invoice_id: str, organization_id: str) -> Invoice | None:
        """Get a specific invoice."""
        return (
            self.db.query(Invoice)
            .filter(
                Invoice.id == invoice_id,
                Invoice.organization_id == organization_id,
            )
            .first()
        )

    def get_invoice_by_number(self, invoice_number: str, organization_id: str) -> Invoice | None:
        """Get an invoice by its number."""
        return (
            self.db.query(Invoice)
            .filter(
                Invoice.invoice_number == invoice_number,
                Invoice.organization_id == organization_id,
            )
            .first()
        )

    def render_invoice_html(self, invoice: Invoice) -> str:
        """Render an invoice as a printable HTML document.

        The HTML is self-contained with inline CSS, suitable for:
        - Browser print-to-PDF (Ctrl+P)
        - Server-side PDF generation (wkhtmltopdf, puppeteer, etc.)
        """
        line_items_html = ""
        items: list[dict[str, Any]] = invoice.line_items or []  # type: ignore[assignment]
        for item in items:
            line_items_html += f"""
            <tr>
                <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;">{item.get("description", "")}</td>
                <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">{item.get("quantity", 1)}</td>
                <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">€{item.get("unit_price_eur", 0):.2f}</td>
                <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">€{item.get("total_eur", 0):.2f}</td>
            </tr>"""

        paid_badge = ""
        if invoice.status == InvoiceStatus.PAID.value:
            paid_badge = '<span style="background:#dcfce7;color:#166534;padding:4px 12px;border-radius:9999px;font-size:12px;font-weight:600;">PAID</span>'
        elif invoice.status == InvoiceStatus.VOID.value:
            paid_badge = '<span style="background:#fee2e2;color:#991b1b;padding:4px 12px;border-radius:9999px;font-size:12px;font-weight:600;">VOID</span>'

        issued_date = invoice.issued_at.strftime("%B %d, %Y") if invoice.issued_at else ""
        paid_date = invoice.paid_at.strftime("%B %d, %Y") if invoice.paid_at else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invoice {invoice.invoice_number}</title>
<style>
  @media print {{
    body {{ margin: 0; }}
    .no-print {{ display: none; }}
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #1f2937;
    line-height: 1.5;
    max-width: 800px;
    margin: 0 auto;
    padding: 40px;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; padding: 10px 12px; border-bottom: 2px solid #1f2937; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; }}
  .totals td {{ padding: 6px 12px; }}
  .totals .total-row td {{ font-weight: 700; font-size: 18px; border-top: 2px solid #1f2937; padding-top: 12px; }}
</style>
</head>
<body>
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:40px;">
    <div>
      <h1 style="font-size:28px;font-weight:800;margin:0;color:#111827;">JAOT</h1>
      <p style="color:#6b7280;margin:4px 0 0;">Optimization as a Service</p>
    </div>
    <div style="text-align:right;">
      <h2 style="font-size:24px;font-weight:700;margin:0;">INVOICE</h2>
      <p style="color:#6b7280;margin:4px 0;">{invoice.invoice_number}</p>
      {paid_badge}
    </div>
  </div>

  <div style="display:flex;justify-content:space-between;margin-bottom:32px;">
    <div>
      <p style="font-size:12px;text-transform:uppercase;color:#6b7280;margin:0 0 4px;">From</p>
      <p style="margin:0;font-weight:600;">JAOT SL</p>
      <p style="margin:0;color:#6b7280;">Barcelona, Spain</p>
      <p style="margin:0;color:#6b7280;">billing@jaot.io</p>
      <p style="margin:0;color:#6b7280;">VAT: ESB12345678</p>
    </div>
    <div style="text-align:right;">
      <p style="font-size:12px;text-transform:uppercase;color:#6b7280;margin:0 0 4px;">Bill To</p>
      <p style="margin:0;font-weight:600;">{invoice.org_name}</p>
      <p style="margin:0;color:#6b7280;">{invoice.org_email or ""}</p>
      <p style="margin:0;color:#6b7280;">Plan: {invoice.org_plan.capitalize()}</p>
    </div>
  </div>

  <div style="display:flex;gap:40px;margin-bottom:32px;">
    <div>
      <p style="font-size:12px;text-transform:uppercase;color:#6b7280;margin:0;">Issue Date</p>
      <p style="margin:4px 0 0;font-weight:500;">{issued_date}</p>
    </div>
    <div>
      <p style="font-size:12px;text-transform:uppercase;color:#6b7280;margin:0;">Payment Date</p>
      <p style="margin:4px 0 0;font-weight:500;">{paid_date or "Pending"}</p>
    </div>
    <div>
      <p style="font-size:12px;text-transform:uppercase;color:#6b7280;margin:0;">Credits Granted</p>
      <p style="margin:4px 0 0;font-weight:500;">{invoice.credits_granted:,}</p>
    </div>
  </div>

  <table style="margin-bottom:24px;">
    <thead>
      <tr>
        <th>Description</th>
        <th style="text-align:center;">Qty</th>
        <th style="text-align:right;">Unit Price</th>
        <th style="text-align:right;">Amount</th>
      </tr>
    </thead>
    <tbody>
      {line_items_html}
    </tbody>
  </table>

  <table class="totals" style="width:300px;margin-left:auto;">
    <tr>
      <td style="color:#6b7280;">Subtotal</td>
      <td style="text-align:right;">€{invoice.subtotal_eur:.2f}</td>
    </tr>
    <tr>
      <td style="color:#6b7280;">Tax ({invoice.tax_rate * 100:.0f}%)</td>
      <td style="text-align:right;">€{invoice.tax_amount_eur:.2f}</td>
    </tr>
    <tr class="total-row">
      <td>Total</td>
      <td style="text-align:right;">€{invoice.total_eur:.2f}</td>
    </tr>
  </table>

  {f'<p style="margin-top:32px;color:#6b7280;font-size:13px;">{invoice.notes}</p>' if invoice.notes else ""}

  <div style="margin-top:48px;padding-top:24px;border-top:1px solid #e5e7eb;color:#9ca3af;font-size:12px;">
    <p>JAOT SL · Barcelona, Spain · billing@jaot.io · jaot.io</p>
    <p>This invoice was generated automatically. For questions, contact billing@jaot.io.</p>
  </div>

  <div class="no-print" style="margin-top:24px;text-align:center;">
    <button onclick="window.print()" style="background:#2563eb;color:white;border:none;padding:10px 24px;border-radius:6px;font-size:14px;cursor:pointer;">
      Print / Save as PDF
    </button>
  </div>
</body>
</html>"""
