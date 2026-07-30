"""Instance-limit error response schemas."""

from typing import Any

from pydantic import BaseModel


class TierCapError(BaseModel):
    """Returned when a request exceeds a limit this instance is configured to enforce.

    ADR-008 removed billing and there are no paid tiers, so this payload no longer
    carries an upsell (``upgrade_to`` / ``upgrade_url`` pointed at a ``/billing`` page
    that no longer exists). ``current_plan`` went the same way: with one set of limits
    per instance, naming a plan alongside a limit only invited the reader to look for
    a bigger one. What a caller actually needs is the limit they hit and the name of
    the setting an administrator can raise — every limit accepts 0 for unlimited.
    """

    error: str  # e.g. "variable_limit_exceeded"
    message: str  # Human-readable explanation
    limit: int | str
    current_value: int | str | None = None
    setting_key: str | None = None  # e.g. "instance_max_variables"


def tier_cap_detail(
    error: str,
    message: str,
    limit: int | str,
    current_value: int | str | None = None,
    setting_key: str | None = None,
) -> dict[str, Any]:
    """Build the limit-exceeded error detail dict for HTTPException."""
    return TierCapError(
        error=error,
        message=message,
        limit=limit,
        current_value=current_value,
        setting_key=setting_key,
    ).model_dump()
