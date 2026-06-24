"""Featured placement service for purchasing and managing model promotions.

Handles placement pricing, purchase with credit deduction, activation/expiry
tracking, and admin revocation/extension.
"""

import logging
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction
from app.models.credit_transaction import TransactionType
from app.models.featured_placement import FeaturedPlacement, PlacementStatus
from app.models.optimization_model import ModelCatalog
from app.schemas.featured_placement import (
    PlacementPricingResponse,
    PlacementPricingTier,
)
from app.services.audit_service import log_action
from app.services.credits_service import CreditsService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)


class FeaturedPlacementService:
    """Service for managing featured placement purchases and lifecycle."""

    # Credits cost per placement type and duration (days)
    PRICING: dict[str, dict[int, int]] = {
        "homepage_carousel": {7: 500, 14: 900, 30: 1200},
        "category_spotlight": {7: 300, 14: 550, 30: 750},
        "search_boost": {7: 200, 14: 350, 30: 500},
        "promoted_badge": {7: 100, 14: 175, 30: 250},
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_pricing(self) -> list[PlacementPricingResponse]:
        """Return all pricing tiers for each placement type."""
        result = []
        for placement_type, tiers in self.PRICING.items():
            tier_list = [
                PlacementPricingTier(duration_days=days, credits_cost=cost)
                for days, cost in sorted(tiers.items())
            ]
            result.append(PlacementPricingResponse(placement_type=placement_type, tiers=tier_list))
        return result

    def purchase(
        self,
        org_id: str,
        user_id: str,
        catalog_model_id: str,
        placement_type: str,
        duration_days: int,
    ) -> FeaturedPlacement:
        """Purchase a featured placement for a model.

        Validates:
        - Model exists and belongs to the org
        - Placement type and duration are valid
        - Org has sufficient credits

        Deducts credits and creates the placement record.
        """
        model = self.db.query(ModelCatalog).filter(ModelCatalog.id == catalog_model_id).first()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        if model.author_organization_id != org_id:
            raise HTTPException(
                status_code=403,
                detail="You can only promote models owned by your organization",
            )

        type_pricing = self.PRICING.get(placement_type)
        if not type_pricing:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid placement type: {placement_type}",
            )
        credits_cost = type_pricing.get(duration_days)
        if credits_cost is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid duration: {duration_days} days for {placement_type}",
            )

        # Deduct credits
        credits_service = CreditsService(self.db)
        credits_service.record_transaction(
            organization_id=org_id,
            transaction_type=TransactionType.FEATURED_PLACEMENT,
            credits_amount=-credits_cost,
            description=f"Featured placement ({placement_type}, {duration_days}d) for {model.display_name}",
            reference_type="featured_placement",
            reference_id=catalog_model_id,
            created_by=user_id,
        )

        now = utcnow()
        placement = FeaturedPlacement(
            id=generate_id("fpl_"),
            catalog_model_id=catalog_model_id,
            organization_id=org_id,
            placement_type=placement_type,
            status=PlacementStatus.ACTIVE.value,
            credits_paid=credits_cost,
            duration_days=duration_days,
            starts_at=now,
            expires_at=now + timedelta(days=duration_days),
            created_by=user_id,
            created_at=now,
        )
        self.db.add(placement)
        self.db.flush()

        logger.info(
            "Placement %s purchased: type=%s, model=%s, org=%s, credits=%d",
            placement.id,
            placement_type,
            catalog_model_id,
            org_id,
            credits_cost,
        )

        return placement

    def get_active_placements(
        self,
        org_id: str | None = None,
        placement_type: str | None = None,
    ) -> list[FeaturedPlacement]:
        """Query active placements. Auto-expires any past their expiry date."""
        now = utcnow()

        # Auto-expire any placements past their expires_at
        expired_count = (
            self.db.query(FeaturedPlacement)
            .filter(
                FeaturedPlacement.status == PlacementStatus.ACTIVE.value,
                FeaturedPlacement.expires_at <= now,
            )
            .update({"status": PlacementStatus.EXPIRED.value})
        )
        if expired_count:
            logger.info("Auto-expired %d placements", expired_count)

        # Query active placements
        q = self.db.query(FeaturedPlacement).filter(
            FeaturedPlacement.status == PlacementStatus.ACTIVE.value,
            FeaturedPlacement.expires_at > now,
        )
        if org_id is not None:
            q = q.filter(FeaturedPlacement.organization_id == org_id)
        if placement_type is not None:
            q = q.filter(FeaturedPlacement.placement_type == placement_type)

        return q.order_by(FeaturedPlacement.created_at.desc()).all()

    def revoke(
        self, placement_id: str, admin_user_id: str, admin_user: object | None = None
    ) -> FeaturedPlacement:
        """Revoke an active placement (admin action)."""
        placement = (
            self.db.query(FeaturedPlacement).filter(FeaturedPlacement.id == placement_id).first()
        )
        if not placement:
            raise HTTPException(status_code=404, detail="Placement not found")
        if placement.status != PlacementStatus.ACTIVE.value:
            raise HTTPException(status_code=400, detail="Only active placements can be revoked")

        now = utcnow()
        placement.status = PlacementStatus.REVOKED.value
        placement.revoked_at = now
        placement.revoked_by = admin_user_id

        # Audit log
        log_action(
            db=self.db,
            organization_id=placement.organization_id,
            actor=admin_user,  # type: ignore[arg-type]
            action=AuditAction.PLACEMENT_REVOKE,
            target_type="featured_placement",
            target_id=placement.id,
            metadata={
                "catalog_model_id": placement.catalog_model_id,
                "placement_type": placement.placement_type,
            },
            actor_id_override=admin_user_id if admin_user is None else None,
            actor_name_override="admin" if admin_user is None else None,
        )

        logger.info("Placement %s revoked by %s", placement_id, admin_user_id)
        return placement

    def extend(self, placement_id: str, extra_days: int, admin_user_id: str) -> FeaturedPlacement:
        """Extend a placement's expiry (admin action)."""
        placement = (
            self.db.query(FeaturedPlacement).filter(FeaturedPlacement.id == placement_id).first()
        )
        if not placement:
            raise HTTPException(status_code=404, detail="Placement not found")

        placement.expires_at = placement.expires_at + timedelta(days=extra_days)
        # Re-activate if it was expired
        if placement.status == PlacementStatus.EXPIRED.value:
            placement.status = PlacementStatus.ACTIVE.value

        logger.info(
            "Placement %s extended by %d days by %s",
            placement_id,
            extra_days,
            admin_user_id,
        )
        return placement
