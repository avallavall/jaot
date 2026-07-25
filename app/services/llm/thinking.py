"""Thinking configuration for Anthropic requests.

Single place that decides how reasoning is requested, because getting it
wrong fails closed in two different ways:

- Manual extended thinking (``{"type": "enabled", "budget_tokens": N}``) is
  rejected with a 400 by every model from Opus 4.7 / Sonnet 5 onwards. The
  replacement is adaptive thinking plus an ``effort`` hint.
- From Sonnet 5 onwards, *omitting* the parameter no longer means "do not
  think" — the model thinks by default. Since ``max_tokens`` caps thinking
  and answer together, a request that used to fit now risks spending its
  budget on reasoning and truncating the JSON. The non-advanced path
  therefore disables thinking explicitly instead of leaving it unset.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Effort levels the API accepts, cheapest first.
VALID_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# API default. Also the fallback for an unrecognised setting value.
DEFAULT_EFFORT = "high"


def resolve_effort(db: Any | None = None) -> str:
    """Read LLM_THINKING_EFFORT, falling back to ``high`` if it is not valid.

    The setting is free-text (the registry has no enum type), so an admin
    typo would otherwise turn every advanced request into a 400.
    """
    from app.services.platform_settings_service import (
        PlatformSettingsService as PSS,
    )

    if db is not None:
        raw = PSS.get_str(db, "LLM_THINKING_EFFORT")
    else:
        from app.shared.db.session import SessionLocal

        _db = SessionLocal()
        try:
            raw = PSS.get_str(_db, "LLM_THINKING_EFFORT")
        finally:
            _db.close()

    effort = (raw or "").strip().lower()
    if effort in VALID_EFFORT_LEVELS:
        return effort

    logger.warning(
        "LLM_THINKING_EFFORT=%r is not one of %s — using %r",
        raw,
        ", ".join(VALID_EFFORT_LEVELS),
        DEFAULT_EFFORT,
        extra={"event_code": "llm.invalid_effort"},
    )
    return DEFAULT_EFFORT


def apply_thinking(
    kwargs: dict[str, Any],
    *,
    thinking: bool,
    db: Any | None = None,
) -> None:
    """Set the thinking (and effort) request fields on *kwargs* in place.

    Args:
        kwargs: Anthropic request kwargs, mutated in place. An existing
            ``output_config`` (e.g. a structured-output ``format``) is
            extended rather than replaced.
        thinking: True for the advanced model — adaptive thinking at the
            configured effort. False for the default model — thinking off.
        db: Optional DB session for runtime settings.
    """
    if not thinking:
        kwargs["thinking"] = {"type": "disabled"}
        return

    kwargs["thinking"] = {"type": "adaptive"}
    output_config = kwargs.setdefault("output_config", {})
    output_config["effort"] = resolve_effort(db)
