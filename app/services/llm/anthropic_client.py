"""Anthropic client factory for LLM-powered formulation generation.

Supports platform-level API key (default) and per-organization BYOK keys.
Uses singleton pattern to reuse client instances.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

# Singleton client cache keyed by API key (thread-safe)
_client_cache: dict[str, AsyncAnthropic] = {}
_client_cache_lock = threading.Lock()


def get_anthropic_client(db: Any | None = None) -> AsyncAnthropic:
    """Get an AsyncAnthropic client using the platform API key.

    When *db* is provided, reads the API key from DB (runtime-configurable).
    Otherwise falls back to the static settings value.

    Returns:
        AsyncAnthropic client instance (cached singleton per key).

    Raises:
        ValueError: If ANTHROPIC_API_KEY is not configured.
    """
    from app.services.platform_settings_service import PlatformSettingsService as PSS

    if db is not None:
        api_key = PSS.get_str(db, "ANTHROPIC_API_KEY")
    else:
        api_key = ""

    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Configure it in .env or via the admin panel."
        )

    return _get_or_create_client(api_key)


def get_anthropic_client_for_org(
    org: Any,
    db: Any | None = None,
) -> AsyncAnthropic:
    """Get an AsyncAnthropic client for a specific organization.

    Uses the organization's own Anthropic API key (BYOK) if set,
    otherwise falls back to the platform key.

    Args:
        org: Organization object (checked for ``anthropic_api_key``).
        db: Optional DB session for runtime settings.

    Returns:
        AsyncAnthropic client instance (cached singleton per key).
    """
    from app.services.platform_settings_service import PlatformSettingsService as PSS

    org_key = getattr(org, "anthropic_api_key", None)
    if org_key:
        api_key = org_key
    elif db is not None:
        api_key = PSS.get_str(db, "ANTHROPIC_API_KEY")
    else:
        api_key = ""

    if not api_key:
        raise ValueError(
            "No Anthropic API key available. Set ANTHROPIC_API_KEY "
            "in .env or configure an organization-level key."
        )

    return _get_or_create_client(api_key)


def _get_or_create_client(api_key: str) -> AsyncAnthropic:
    """Get or create a cached AsyncAnthropic client for the given key."""
    if api_key in _client_cache:
        return _client_cache[api_key]

    with _client_cache_lock:
        # Double-checked locking
        if api_key not in _client_cache:
            _client_cache[api_key] = AsyncAnthropic(api_key=api_key)
            logger.debug("Created new Anthropic client (key=%s...)", api_key[:8])

    return _client_cache[api_key]


def clear_client_cache() -> None:
    """Clear the client cache. Useful for testing."""
    _client_cache.clear()
