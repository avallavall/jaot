"""Tests for featured placement purchase, expiry, and admin revocation.

Covers:
- Successful placement purchase with credit deduction
- Purchase failure with insufficient credits
- Purchase failure for non-owned model
- Active placements query excludes expired placements
- Admin revoke changes status and sets revoked_by
"""

from datetime import timedelta

import pytest

from app.models import ModelCatalog, Organization, User
from app.models.featured_placement import FeaturedPlacement, PlacementStatus
from app.services.featured_placement_service import FeaturedPlacementService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def placement_org(db_session):
    """Create an organization with enough credits for placement purchases."""
    org = Organization(
        id="org_placement001",
        name="Placement Seller",
        credits_balance=5000,
        credits_earned=0,
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def placement_user(db_session, placement_org):
    """Create a seller user for placement tests."""
    user = User(
        id="user_placement001",
        email="placement@example.com",
        name="Placement User",
        organization_id=placement_org.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def placement_model(db_session, placement_org):
    """Create a published catalog model owned by the placement org."""
    model = ModelCatalog(
        id="cat_placement001",
        name="placement-model",
        display_name="Placement Test Model",
        description="A model for placement tests",
        category="linear",
        generator_type="linear_programming",
        input_schema={"type": "object", "properties": {}},
        input_fields=[],
        example_input={},
        status="published",
        is_public=True,
        price_eur=10.0,
        author_organization_id=placement_org.id,
        total_activations=0,
        total_executions=0,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


@pytest.fixture
def other_org_model(db_session, test_organization):
    """Create a model owned by a different organization."""
    model = ModelCatalog(
        id="cat_other001",
        name="other-model",
        display_name="Other Org Model",
        description="Model owned by another org",
        category="linear",
        generator_type="linear_programming",
        input_schema={"type": "object", "properties": {}},
        input_fields=[],
        example_input={},
        status="published",
        is_public=True,
        price_eur=5.0,
        author_organization_id=test_organization.id,
        total_activations=0,
        total_executions=0,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


class TestPlacementPurchase:
    """Test successful and failed placement purchases."""

    def test_purchase_creates_placement_and_deducts_credits(
        self, db_session, placement_org, placement_user, placement_model
    ):
        """Successful purchase creates an active placement and deducts credits."""
        initial_balance = placement_org.credits_balance
        service = FeaturedPlacementService(db_session)
        placement = service.purchase(
            org_id=placement_org.id,
            user_id=placement_user.id,
            catalog_model_id=placement_model.id,
            placement_type="homepage_carousel",
            duration_days=7,
        )
        db_session.commit()

        assert placement is not None
        assert placement.status == PlacementStatus.ACTIVE.value
        assert placement.credits_paid == 500
        assert placement.placement_type == "homepage_carousel"
        assert placement.duration_days == 7
        assert placement.catalog_model_id == placement_model.id

        # Credits should be deducted
        db_session.refresh(placement_org)
        assert placement_org.credits_balance == initial_balance - 500

    def test_purchase_fails_insufficient_credits(
        self, db_session, placement_org, placement_user, placement_model
    ):
        """Purchase fails when organization has insufficient credits."""
        # Set balance to 0
        placement_org.credits_balance = 0
        db_session.commit()

        from app.services.credits_service import InsufficientCreditsError

        service = FeaturedPlacementService(db_session)
        with pytest.raises(InsufficientCreditsError) as exc_info:
            service.purchase(
                org_id=placement_org.id,
                user_id=placement_user.id,
                catalog_model_id=placement_model.id,
                placement_type="homepage_carousel",
                duration_days=7,
            )
        assert exc_info.value.credits_available == 0
        assert exc_info.value.credits_needed > 0

    def test_purchase_fails_non_owned_model(
        self, db_session, placement_org, placement_user, other_org_model
    ):
        """Purchase fails when trying to promote a model owned by another org."""
        from fastapi import HTTPException

        service = FeaturedPlacementService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            service.purchase(
                org_id=placement_org.id,
                user_id=placement_user.id,
                catalog_model_id=other_org_model.id,
                placement_type="homepage_carousel",
                duration_days=7,
            )
        assert exc_info.value.status_code == 403


class TestPlacementExpiry:
    """Test placement expiry and filtering."""

    def test_get_active_placements_excludes_expired(
        self, db_session, placement_org, placement_model
    ):
        """Active placements query does not return expired placements."""
        now = utcnow()
        expired = FeaturedPlacement(
            id=generate_id("fpl_"),
            catalog_model_id=placement_model.id,
            organization_id=placement_org.id,
            placement_type="homepage_carousel",
            status=PlacementStatus.ACTIVE.value,
            credits_paid=500,
            duration_days=7,
            starts_at=now - timedelta(days=10),
            expires_at=now - timedelta(days=3),
            created_by="system",
            created_at=now - timedelta(days=10),
        )
        db_session.add(expired)
        db_session.commit()

        service = FeaturedPlacementService(db_session)
        active = service.get_active_placements(org_id=placement_org.id)
        assert len(active) == 0

        # The expired placement should have been auto-updated
        db_session.refresh(expired)
        assert expired.status == PlacementStatus.EXPIRED.value

    def test_active_placement_returned(self, db_session, placement_org, placement_model):
        """A non-expired active placement is returned."""
        now = utcnow()
        active_placement = FeaturedPlacement(
            id=generate_id("fpl_"),
            catalog_model_id=placement_model.id,
            organization_id=placement_org.id,
            placement_type="category_spotlight",
            status=PlacementStatus.ACTIVE.value,
            credits_paid=300,
            duration_days=7,
            starts_at=now,
            expires_at=now + timedelta(days=7),
            created_by="system",
            created_at=now,
        )
        db_session.add(active_placement)
        db_session.commit()

        service = FeaturedPlacementService(db_session)
        active = service.get_active_placements(org_id=placement_org.id)
        assert len(active) == 1
        assert active[0].id == active_placement.id


class TestAdminRevoke:
    """Test admin revocation of placements."""

    def test_revoke_changes_status(self, db_session, placement_org, placement_model):
        """Admin revoke changes placement status to revoked."""
        now = utcnow()
        placement = FeaturedPlacement(
            id=generate_id("fpl_"),
            catalog_model_id=placement_model.id,
            organization_id=placement_org.id,
            placement_type="search_boost",
            status=PlacementStatus.ACTIVE.value,
            credits_paid=200,
            duration_days=7,
            starts_at=now,
            expires_at=now + timedelta(days=7),
            created_by="system",
            created_at=now,
        )
        db_session.add(placement)
        db_session.commit()

        service = FeaturedPlacementService(db_session)
        revoked = service.revoke(placement.id, "admin_user_001")
        db_session.commit()

        assert revoked.status == PlacementStatus.REVOKED.value
        assert revoked.revoked_by == "admin_user_001"
        assert revoked.revoked_at is not None
