"""BYOK (bring-your-own-key) for the Anthropic API — organization level.

The platform ships with a single shared Anthropic key (``ANTHROPIC_API_KEY`` in
platform settings) that the operator pays for. To avoid that bill being the only
funding source, an organization can store **its own** Anthropic key. Resolution is
**BYOK-first**: if an org has set its own key, every LLM call for that org runs on
*their* account (free for the platform, no platform-budget consumption, no JAOT
credits charged). Orgs without a key fall back to the shared platform key, still
gated by the monthly platform budget.

The org key is a third-party credential, so it is **encrypted at rest** with Fernet.
The encryption key is derived from ``JWT_SECRET`` (already required infra config) so
no extra env var / deploy step is needed; rotating ``JWT_SECRET`` simply invalidates
stored keys and the owner re-enters them. The plaintext key is never returned by any
API response (only a masked hint) and never logged.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

# Anthropic keys look like ``sk-ant-...``; used for a friendly client-side check.
ANTHROPIC_KEY_PREFIX = "sk-ant-"


def _fernet() -> Fernet:
    """Build a Fernet from a stable 32-byte key derived from ``JWT_SECRET``.

    Deriving from JWT_SECRET keeps BYOK encryption keyless-of-its-own-config: no
    separate secret to provision. The trade-off (rotating JWT_SECRET invalidates
    stored keys) is acceptable for re-enterable API keys.
    """
    digest = hashlib.sha256(settings.jwt_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt a plaintext API key for storage. Returns an opaque token string."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_api_key(token: str | None) -> str | None:
    """Decrypt a stored token back to the plaintext key, or None if absent/invalid."""
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        # JWT_SECRET rotated, or corrupted ciphertext — treat as "no key".
        logger.warning("Could not decrypt an organization Anthropic key; treating as unset.")
        return None


def mask_api_key(plaintext: str | None) -> str | None:
    """Return a non-sensitive display hint (last 4 chars), or None when unset."""
    if not plaintext:
        return None
    return f"{ANTHROPIC_KEY_PREFIX}…{plaintext[-4:]}"


def get_org_api_key(org: Any) -> str | None:
    """Decrypt and return the org's own Anthropic key, or None when not set."""
    return decrypt_api_key(getattr(org, "anthropic_api_key_encrypted", None))


def org_has_byok(org: Any) -> bool:
    """True when the org has a stored Anthropic key (no decryption needed)."""
    return bool(getattr(org, "anthropic_api_key_encrypted", None))


def resolve_anthropic_client(org: Any) -> tuple[AsyncAnthropic | None, bool]:
    """Resolve the Anthropic client to use for an org's LLM call (BYOK-first).

    Returns ``(client, is_byok)``:
    - BYOK: ``(org_client, True)`` — the call runs on the org's own account, so the
      caller must skip the platform budget guardrail and skip charging JAOT credits.
    - Platform: ``(None, False)`` — the caller passes ``client=None`` to the generation
      functions, which then create the shared platform client via the (test-patchable)
      ``get_anthropic_client(db)``. Returning None here intentionally preserves that
      indirection so existing tests that patch ``get_anthropic_client`` keep working.
    """
    key = get_org_api_key(org)
    if key:
        from app.services.llm.anthropic_client import _get_or_create_client  # noqa: PLC0415

        return _get_or_create_client(key), True
    return None, False
