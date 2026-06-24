"""
Tests for the invoice service and billing invoice endpoints.

Covers:
- Invoice creation (subscription, top-up, adjustment) against REAL PostgreSQL
- Invoice numbering (DB sequence driven, per-year format)
- Invoice retrieval (list, single, by number)
- HTML rendering (structure, line items, totals, paid badge)
- Edge cases (unknown plan, invalid top-up)
- Pricing consistency with PRICING.md
"""

import pytest
from sqlalchemy.orm import Session

from app.models import Organization
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services.invoice_service import (
    PLAN_PRICES_EUR,
    TOPUP_PRICES_EUR,
    InvoiceService,
)
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def invoice_org(db_session: Session) -> Organization:
    """Persisted test organization for invoice tests."""
    org = Organization(
        id=generate_id("org_"),
        name="Test Corp",
        plan="pro",
        currency="EUR",
        billing_email="billing@test.com",
        credits_balance=0,
        credits_earned=0,
        monthly_quota=100,
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


class TestSubscriptionInvoice:
    def test_create_starter_monthly(self, db_session: Session, invoice_org: Organization):
        """Starter monthly invoice is persisted with the correct fields."""
        invoice_org.plan = "starter"
        db_session.commit()

        service = InvoiceService(db_session)
        invoice = service.create_subscription_invoice(invoice_org, plan="starter", annual=False)

        # Re-fetch from DB to prove persistence.
        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.organization_id == invoice_org.id
        assert fetched.invoice_type == InvoiceType.SUBSCRIPTION.value
        assert fetched.status == InvoiceStatus.PAID.value
        assert fetched.subtotal_eur == 19.0
        assert fetched.total_eur == 19.0
        assert fetched.credits_granted == 600
        assert fetched.org_name == "Test Corp"
        assert len(fetched.line_items) == 1
        assert "Starter" in fetched.line_items[0]["description"]

    def test_create_pro_annual(self, db_session: Session, invoice_org: Organization):
        """Pro annual invoice grants 12x monthly credits and uses annual price."""
        invoice_org.plan = "pro"
        db_session.commit()

        service = InvoiceService(db_session)
        invoice = service.create_subscription_invoice(invoice_org, plan="pro", annual=True)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.subtotal_eur == 490.0
        assert fetched.credits_granted == 2500 * 12  # 30,000 credits
        assert "annual" in fetched.line_items[0]["description"].lower()

    def test_create_business_monthly(self, db_session: Session, invoice_org: Organization):
        """Business monthly invoice is persisted with the correct fields."""
        invoice_org.plan = "business"
        db_session.commit()

        service = InvoiceService(db_session)
        invoice = service.create_subscription_invoice(invoice_org, plan="business")

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.subtotal_eur == 149.0
        assert fetched.credits_granted == 20000

    def test_unknown_plan_raises(self, db_session: Session, invoice_org: Organization):
        """Unknown plan names must raise ValueError — no DB persistence required."""
        service = InvoiceService(db_session)
        with pytest.raises(ValueError, match="Unknown plan"):
            service.create_subscription_invoice(invoice_org, plan="ultra_mega")

    def test_stripe_ids_stored(self, db_session: Session, invoice_org: Organization):
        """Stripe invoice_id and payment_intent_id round-trip through the DB."""
        service = InvoiceService(db_session)
        invoice = service.create_subscription_invoice(
            invoice_org,
            plan="starter",
            stripe_invoice_id="inv_stripe_123",
            stripe_payment_intent_id="pi_stripe_456",
        )

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.stripe_invoice_id == "inv_stripe_123"
        assert fetched.stripe_payment_intent_id == "pi_stripe_456"


class TestTopupInvoice:
    def test_create_500_credits(self, db_session: Session, invoice_org: Organization):
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.invoice_type == InvoiceType.TOPUP.value
        assert fetched.subtotal_eur == 14.0
        assert fetched.credits_granted == 500
        assert "500" in fetched.line_items[0]["description"]

    def test_create_2000_credits(self, db_session: Session, invoice_org: Organization):
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=2000)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.subtotal_eur == 48.0
        assert fetched.credits_granted == 2000

    def test_create_5000_credits(self, db_session: Session, invoice_org: Organization):
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=5000)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.subtotal_eur == 100.0
        assert fetched.credits_granted == 5000

    def test_create_20000_credits(self, db_session: Session, invoice_org: Organization):
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=20000)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.subtotal_eur == 320.0
        assert fetched.credits_granted == 20000

    def test_invalid_topup_amount_raises(self, db_session: Session, invoice_org: Organization):
        """Top-up amount not in the price table must raise ValueError."""
        service = InvoiceService(db_session)
        with pytest.raises(ValueError, match="Invalid top-up amount"):
            service.create_topup_invoice(invoice_org, credits=999)

    def test_unit_price_calculated(self, db_session: Session, invoice_org: Organization):
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        unit_price = invoice.line_items[0]["unit_price_eur"]
        assert unit_price == pytest.approx(14.0 / 500, abs=0.001)


class TestAdjustmentInvoice:
    def test_create_adjustment(self, db_session: Session, invoice_org: Organization):
        """Admin adjustment invoice persists with the supplied description and credits."""
        service = InvoiceService(db_session)
        invoice = service.create_adjustment_invoice(
            invoice_org,
            description="Promotional credits",
            amount_eur=0.0,
            credits=500,
        )

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.invoice_type == InvoiceType.ADJUSTMENT.value
        assert fetched.credits_granted == 500
        assert fetched.subtotal_eur == 0.0
        assert fetched.line_items[0]["description"] == "Promotional credits"


class TestInvoiceNumbering:
    def test_first_invoice_number(self, db_session: Session, invoice_org: Organization):
        """First invoice on a fresh org uses the real postgres sequence."""
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.invoice_number.startswith("INV-")
        # Cannot pin the sequence value (shared across test suite) but
        # format must contain the zero-padded numeric suffix.
        parts = fetched.invoice_number.split("-")
        assert len(parts) == 3
        assert len(parts[2]) == 5
        assert parts[2].isdigit()

    def test_invoice_number_contains_year(self, db_session: Session, invoice_org: Organization):
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        year = utcnow().strftime("%Y")
        assert year in fetched.invoice_number


class TestInvoiceFields:
    def test_tax_defaults_to_zero(self, db_session: Session, invoice_org: Organization):
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.tax_rate == 0.0
        assert fetched.tax_amount_eur == 0.0
        assert fetched.total_eur == fetched.subtotal_eur

    def test_org_snapshot_captured(self, db_session: Session, invoice_org: Organization):
        """Org name / email / plan are snapshotted onto the invoice row."""
        invoice_org.name = "Acme Corp"
        invoice_org.billing_email = "acme@test.com"
        invoice_org.plan = "pro"
        db_session.commit()

        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.org_name == "Acme Corp"
        assert fetched.org_email == "acme@test.com"
        assert fetched.org_plan == "pro"

    def test_currency_from_org(self, db_session: Session, invoice_org: Organization):
        invoice_org.currency = "USD"
        db_session.commit()

        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.currency == "USD"

    def test_paid_at_set(self, db_session: Session, invoice_org: Organization):
        """paid_at and issued_at are recent (within 5 seconds of utcnow)."""
        from datetime import timedelta

        before = utcnow()
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.paid_at is not None
        assert fetched.issued_at is not None

        # paid_at must be recent (within 5 seconds of before)
        # DB values may be timezone-naive; normalise both sides for comparison.
        paid_at = fetched.paid_at
        if paid_at.tzinfo is None:
            before_naive = before.replace(tzinfo=None)
            delta = abs((paid_at - before_naive).total_seconds())
        else:
            delta = abs((paid_at - before).total_seconds())
        assert delta < 5, f"paid_at drift of {delta}s is too large"

        issued_at = fetched.issued_at
        if issued_at.tzinfo is None:
            before_naive = before.replace(tzinfo=None)
            delta = abs((issued_at - before_naive).total_seconds())
        else:
            delta = abs((issued_at - before).total_seconds())
        assert delta < 5, f"issued_at drift of {delta}s is too large"

        # due_at must be > paid_at (grace period).
        assert fetched.due_at > fetched.paid_at
        assert fetched.due_at <= fetched.paid_at + timedelta(days=31)

    def test_invoice_id_format(self, db_session: Session, invoice_org: Organization):
        """Invoice ID respects the prefixed-ID convention from CLAUDE.md."""
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=500)

        fetched = db_session.query(Invoice).filter(Invoice.id == invoice.id).one()
        assert fetched.id.startswith("inv_")


# HTML RENDERING — Driven by a real persisted invoice


class TestInvoiceHTML:
    @pytest.fixture
    def html_invoice(self, db_session: Session, invoice_org: Organization):
        service = InvoiceService(db_session)
        invoice = service.create_topup_invoice(invoice_org, credits=2000)
        return service, invoice

    def test_html_contains_invoice_number(self, html_invoice):
        service, invoice = html_invoice
        html = service.render_invoice_html(invoice)
        assert invoice.invoice_number in html

    def test_html_contains_org_name(self, html_invoice):
        service, invoice = html_invoice
        html = service.render_invoice_html(invoice)
        assert "Test Corp" in html

    def test_html_contains_total(self, html_invoice):
        service, invoice = html_invoice
        html = service.render_invoice_html(invoice)
        assert "€48.00" in html

    def test_html_contains_paid_badge(self, html_invoice):
        service, invoice = html_invoice
        html = service.render_invoice_html(invoice)
        assert "PAID" in html

    def test_html_contains_line_items(self, html_invoice):
        service, invoice = html_invoice
        html = service.render_invoice_html(invoice)
        assert "Credit Top-Up" in html
        assert "2,000" in html

    def test_html_contains_jaot_branding(self, html_invoice):
        service, invoice = html_invoice
        html = service.render_invoice_html(invoice)
        assert "JAOT" in html
        assert "billing@jaot.io" in html

    def test_void_invoice_badge(self, html_invoice, db_session: Session):
        """Voiding an invoice renders the VOID badge in the HTML output."""
        service, invoice = html_invoice
        invoice.status = InvoiceStatus.VOID.value
        db_session.flush()

        html = service.render_invoice_html(invoice)
        assert "VOID" in html


class TestPricingConsistency:
    def test_plan_prices_match_docs(self):
        assert PLAN_PRICES_EUR["starter"]["monthly"] == 19.0
        assert PLAN_PRICES_EUR["pro"]["monthly"] == 49.0
        assert PLAN_PRICES_EUR["business"]["monthly"] == 149.0

    def test_plan_credits_match_docs(self):
        assert PLAN_PRICES_EUR["starter"]["credits"] == 600
        assert PLAN_PRICES_EUR["pro"]["credits"] == 2500
        assert PLAN_PRICES_EUR["business"]["credits"] == 20000

    def test_topup_prices_match_docs(self):
        assert TOPUP_PRICES_EUR[500] == 14.0
        assert TOPUP_PRICES_EUR[2000] == 48.0
        assert TOPUP_PRICES_EUR[5000] == 100.0
        assert TOPUP_PRICES_EUR[20000] == 320.0

    def test_topup_price_per_credit_decreases(self):
        prices_per_credit = {k: v / k for k, v in TOPUP_PRICES_EUR.items()}
        amounts = sorted(TOPUP_PRICES_EUR.keys())
        for i in range(len(amounts) - 1):
            assert prices_per_credit[amounts[i]] > prices_per_credit[amounts[i + 1]], (
                f"Price per credit should decrease: {amounts[i]} vs {amounts[i + 1]}"
            )


class TestInvoiceListing:
    def test_get_invoices_scoped_by_org_and_offset(
        self, db_session: Session, invoice_org: Organization
    ):
        """get_invoices scopes by org and honors the offset default.

        Kills the invoice_service.get_invoices ``offset=0 -> 1`` mutant
        (mutmut-v24 section 3): with the default offset=0 every row returns, so a
        flipped default would silently drop the newest invoice. get_invoices had
        no direct test. Also pins org-scoping (no cross-tenant leak) + ordering.
        """
        from datetime import timedelta

        now = utcnow()

        def _inv(org_id: str, number: str, issued_at: object) -> None:
            db_session.add(
                Invoice(
                    id=generate_id("inv_"),
                    invoice_number=number,
                    organization_id=org_id,
                    invoice_type=InvoiceType.SUBSCRIPTION.value,
                    org_name="Test Corp",
                    org_plan="pro",
                    issued_at=issued_at,
                )
            )

        other = Organization(
            id=generate_id("org_"),
            name="Other Inv Org",
            plan="pro",
            currency="EUR",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            is_active=True,
        )
        db_session.add(other)
        db_session.flush()

        # Three invoices for invoice_org with strictly increasing issued_at.
        _inv(invoice_org.id, "INV-LIST-001", now - timedelta(days=2))
        _inv(invoice_org.id, "INV-LIST-002", now - timedelta(days=1))
        _inv(invoice_org.id, "INV-LIST-003", now)  # newest
        _inv(other.id, "INV-LIST-OTHER", now)
        db_session.commit()

        service = InvoiceService(db_session)

        # Default offset=0 -> all 3 of this org's invoices (kills offset=1).
        all_inv = service.get_invoices(invoice_org.id)
        assert len(all_inv) == 3
        assert all(inv.organization_id == invoice_org.id for inv in all_inv)
        # Ordered newest-first (desc issued_at).
        assert all_inv[0].invoice_number == "INV-LIST-003"

        # offset=1 skips exactly the newest invoice (proves offset is honored).
        offset1 = service.get_invoices(invoice_org.id, offset=1)
        assert len(offset1) == 2
        assert offset1[0].invoice_number == "INV-LIST-002"
