"""Public pricing API endpoint.

Returns plan tiers with credits, prices, limits, and features.
All values are read from PlatformSettingsService (DB + registry).
"""

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_monetization_enabled
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pricing", tags=["pricing"])

_TIERS = ("free", "starter", "pro", "business")

_TIER_NAMES = {
    "free": "Free",
    "starter": "Starter",
    "pro": "Pro",
    "business": "Business",
}


class PricingTier(BaseModel):
    """A single plan tier with all pricing and limit data."""

    slug: str = Field(..., description="Tier identifier")
    name: str = Field(..., description="Display name")
    monthly_price: int = Field(..., description="Monthly price in whole currency units")
    annual_price: int = Field(..., description="Annual price in whole currency units")
    credits: int = Field(..., description="Monthly credit allocation")
    monthly_quota: int = Field(..., description="Monthly usage quota")
    rate_limit_per_minute: int = Field(..., description="API calls per minute")
    rate_limit_per_day: int = Field(..., description="API calls per day")
    max_variables: int = Field(..., description="Maximum decision variables")
    max_solve_time_seconds: int = Field(..., description="Max solver time in seconds")
    max_daily_solves: int = Field(..., description="Maximum solves per day")
    max_cron_schedules: int = Field(..., description="Maximum cron schedules")
    allowed_features: list[str] = Field(
        default_factory=list,
        description="List of allowed feature slugs",
    )


class PricingResponse(BaseModel):
    """Public pricing data for all plan tiers."""

    tiers: list[PricingTier]


@router.get(
    "",
    response_model=PricingResponse,
    summary="Get public pricing data",
    description=(
        "Returns pricing tiers with credits, prices, limits, and "
        "features. All values are read from the platform settings "
        "database. No authentication required. Only available when "
        "monetization is enabled; the free collaborative deployment "
        "responds 404."
    ),
    dependencies=[Depends(require_monetization_enabled)],
)
def get_pricing(db: Session = Depends(get_db)) -> JSONResponse:
    """Return pricing data for all plan tiers.

    Public endpoint — no authentication required.
    Cached for 5 minutes via Cache-Control header.
    """
    # Batch-fetch all price keys for all tiers in a single DB query
    price_keys = []
    for slug in _TIERS:
        price_keys.append(f"plan_{slug}_monthly_price")
        if slug != "free":
            price_keys.append(f"plan_{slug}_annual_price")
    price_values = PSS.get_many(db, price_keys)

    tiers: list[PricingTier] = []

    for slug in _TIERS:
        plan_config = PSS.get_plan_config_dynamic(db, slug)

        try:
            monthly_price = int(price_values.get(f"plan_{slug}_monthly_price", "0"))
        except (ValueError, TypeError):
            monthly_price = 0

        if slug == "free":
            annual_price = 0
        else:
            try:
                annual_price = int(price_values.get(f"plan_{slug}_annual_price", "0"))
            except (ValueError, TypeError):
                annual_price = 0

        allowed_features = plan_config.get("allowed_features", [])
        if isinstance(allowed_features, str):
            try:
                allowed_features = json.loads(allowed_features)
            except (ValueError, TypeError):
                allowed_features = []

        tiers.append(
            PricingTier(
                slug=slug,
                name=_TIER_NAMES[slug],
                monthly_price=monthly_price,
                annual_price=annual_price,
                credits=plan_config.get("credits", 0),
                monthly_quota=plan_config.get("monthly_quota", 0),
                rate_limit_per_minute=plan_config.get("rate_limit_per_minute", 0),
                rate_limit_per_day=plan_config.get("rate_limit_per_day", 0),
                max_variables=plan_config.get("max_variables", 0),
                max_solve_time_seconds=plan_config.get("max_solve_time_seconds", 0),
                max_daily_solves=plan_config.get("max_daily_solves", 0),
                max_cron_schedules=plan_config.get("max_cron_schedules", 0),
                allowed_features=allowed_features,
            )
        )

    response_data = PricingResponse(tiers=tiers)

    return JSONResponse(
        content=response_data.model_dump(),
        headers={"Cache-Control": "public, max-age=300"},
    )
