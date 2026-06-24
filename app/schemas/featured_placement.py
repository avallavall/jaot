"""Pydantic schemas for featured placement API requests and responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PlacementPricingTier(BaseModel):
    """Pricing tier for a placement duration."""

    duration_days: int
    credits_cost: int


class PlacementPricingResponse(BaseModel):
    """Pricing for a specific placement type."""

    placement_type: str
    tiers: list[PlacementPricingTier]


class PurchasePlacementRequest(BaseModel):
    """Request to purchase a featured placement."""

    catalog_model_id: str
    placement_type: str
    duration_days: Literal[7, 14, 30]


class FeaturedPlacementResponse(BaseModel):
    """Featured placement details."""

    id: str
    catalog_model_id: str
    placement_type: str
    status: str
    credits_paid: int
    duration_days: int
    starts_at: datetime
    expires_at: datetime
    created_at: datetime


class ActivePlacementsResponse(BaseModel):
    """List of active placements."""

    items: list[FeaturedPlacementResponse]
    total: int


class AdminPlacementResponse(FeaturedPlacementResponse):
    """Extended placement details for admin view."""

    org_name: str | None = None
    model_name: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
