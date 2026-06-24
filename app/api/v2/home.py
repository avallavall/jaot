"""Public home page endpoints.

Currently exposes a single endpoint for the announcement banner shown on
public pages. The banner content is admin-editable via platform settings
and read here without authentication so the frontend can render it on
the homepage / public layout for visitors.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import DBSession
from app.services.platform_settings_service import (
    PlatformSettingsService as PSS,
)

router = APIRouter(prefix="/home", tags=["home"])


# Locales supported by the frontend (see frontend/messages/*.json)
_SUPPORTED_LOCALES = frozenset({"en", "es", "ca", "fr", "de"})


class HomeAnnouncementResponse(BaseModel):
    """Content for the public announcement banner."""

    enabled: bool
    messages: list[str]
    rotation_seconds: int


@router.get("/announcement", response_model=HomeAnnouncementResponse)
def get_home_announcement(
    db: DBSession,
    locale: str = Query(
        "en",
        description="Locale code (en, es, ca, fr, de). Falls back to en for unknown.",
    ),
) -> HomeAnnouncementResponse:
    """Return the announcement banner content for a given locale.

    Public endpoint — no authentication required. Returns ``enabled=false``
    when the banner is globally disabled or when the locale-specific text
    is empty. The text is split on ``|`` for rotation; whitespace-only
    fragments are dropped.
    """
    if locale not in _SUPPORTED_LOCALES:
        locale = "en"

    text_key = f"HOME_ANNOUNCEMENT_TEXT_{locale.upper()}"
    # One SELECT for all three settings instead of three round-trips on the
    # public home render path (which has no client cache: 'no-store').
    rows = PSS.get_many(
        db,
        ["HOME_ANNOUNCEMENT_ENABLED", "HOME_ANNOUNCEMENT_ROTATION_SECONDS", text_key],
    )
    enabled = rows.get("HOME_ANNOUNCEMENT_ENABLED", "false").lower() in ("true", "1", "yes")
    rotation = int(rows.get("HOME_ANNOUNCEMENT_ROTATION_SECONDS") or 5)

    if not enabled:
        return HomeAnnouncementResponse(enabled=False, messages=[], rotation_seconds=rotation)

    raw = rows.get(text_key, "")
    messages = [m.strip() for m in raw.split("|") if m.strip()]

    return HomeAnnouncementResponse(
        enabled=bool(messages),
        messages=messages,
        rotation_seconds=rotation,
    )
