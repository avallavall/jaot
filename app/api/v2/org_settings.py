"""Organization settings — BYOK Anthropic API key management.

Lets the organization owner store/clear the org's own Anthropic API key so the org's
LLM calls run on its own account (BYOK-first; see app/services/llm/byok.py). The key
is Fernet-encrypted at rest, never returned in plaintext (only a masked hint), and
never logged. Reads are available to any org member (so the UI can show whether BYOK
is active); writes require the org owner.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentOrg, CurrentUser, DBSession, OrgOwnerUser
from app.models import Organization
from app.services.llm.byok import (
    ANTHROPIC_KEY_PREFIX,
    encrypt_api_key,
    get_org_api_key,
    mask_api_key,
)

router = APIRouter(prefix="/organization", tags=["organization"])


class SetAnthropicKeyRequest(BaseModel):
    """Body for storing the org's own Anthropic API key."""

    api_key: str = Field(
        ...,
        min_length=20,
        max_length=300,
        description="The organization's Anthropic API key (starts with 'sk-ant-').",
    )


def _key_status(org: Organization, *, include_hint: bool) -> dict[str, Any]:
    """Build the masked status payload. The plaintext key is never returned."""
    plaintext = get_org_api_key(org)
    return {
        "enabled": bool(plaintext),
        "hint": mask_api_key(plaintext) if include_hint else None,
    }


@router.get("/anthropic-key")
def get_anthropic_key_status(
    db: DBSession,
    org: CurrentOrg,
    user: CurrentUser,
) -> dict[str, Any]:
    """Whether the org has a BYOK key set. The owner also sees a masked hint."""
    is_owner = org.owner_user_id == user.id
    return _key_status(org, include_hint=is_owner)


@router.put("/anthropic-key")
def set_anthropic_key(
    body: SetAnthropicKeyRequest,
    db: DBSession,
    org: CurrentOrg,
    _owner: OrgOwnerUser,
) -> dict[str, Any]:
    """Store the org's Anthropic API key (encrypted). Owner only."""
    key = body.api_key.strip()
    if not key.startswith(ANTHROPIC_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Anthropic API keys start with '{ANTHROPIC_KEY_PREFIX}'.",
        )
    org.anthropic_api_key_encrypted = encrypt_api_key(key)
    db.commit()
    db.refresh(org)
    return _key_status(org, include_hint=True)


@router.delete("/anthropic-key")
def clear_anthropic_key(
    db: DBSession,
    org: CurrentOrg,
    _owner: OrgOwnerUser,
) -> dict[str, Any]:
    """Remove the org's BYOK key — the org falls back to the platform key. Owner only."""
    org.anthropic_api_key_encrypted = None
    db.commit()
    db.refresh(org)
    return _key_status(org, include_hint=True)
