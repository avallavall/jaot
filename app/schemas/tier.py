"""Tier cap error response schemas."""

from typing import Any

from pydantic import BaseModel


class TierCapError(BaseModel):
    """Returned when a request exceeds a tier cap."""

    error: str  # e.g. "variable_limit_exceeded"
    message: str  # Human-readable explanation
    current_plan: str
    limit: int | str
    current_value: int | str | None = None
    upgrade_to: str  # e.g. "Starter"
    upgrade_url: str = "/billing"


def tier_cap_detail(
    error: str,
    message: str,
    current_plan: str,
    limit: int | str,
    current_value: int | str | None = None,
) -> dict[str, Any]:
    """Build tier cap error detail dict for HTTPException."""
    upgrade_map = {
        "free": "Starter",
        "starter": "Pro",
        "pro": "Business",
        "business": "Business",
    }
    return TierCapError(
        error=error,
        message=message,
        current_plan=current_plan,
        limit=limit,
        current_value=current_value,
        upgrade_to=upgrade_map.get(current_plan, "Business"),
    ).model_dump()
