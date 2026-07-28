"""Instance-limit error response schemas."""

from typing import Any

from pydantic import BaseModel


class TierCapError(BaseModel):
    """Returned when a request exceeds a limit this instance is configured to enforce.

    ADR-008 removed billing and there are no paid tiers, so this payload no longer
    carries an upsell (``upgrade_to`` / ``upgrade_url`` pointed at a ``/billing`` page
    that no longer exists). What a caller actually needs is the limit they hit and the
    name of the setting an administrator can raise — every limit accepts 0 for
    unlimited.
    """

    error: str  # e.g. "variable_limit_exceeded"
    message: str  # Human-readable explanation
    current_plan: str
    limit: int | str
    current_value: int | str | None = None
    setting_key: str | None = None  # e.g. "instance_max_variables"


def tier_cap_detail(
    error: str,
    message: str,
    current_plan: str,
    limit: int | str,
    current_value: int | str | None = None,
    setting_key: str | None = None,
) -> dict[str, Any]:
    """Build the limit-exceeded error detail dict for HTTPException."""
    return TierCapError(
        error=error,
        message=message,
        current_plan=current_plan,
        limit=limit,
        current_value=current_value,
        setting_key=setting_key,
    ).model_dump()
