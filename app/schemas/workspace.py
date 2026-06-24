"""Pydantic v2 schemas for workspace collaboration API endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

_VALID_ROLES = {"admin", "editor", "solver", "viewer"}


def _validate_role(v: str) -> str:
    if v not in _VALID_ROLES:
        raise ValueError(f"role must be one of: {', '.join(sorted(_VALID_ROLES))}")
    return v


class WorkspaceCreate(BaseModel):
    """Request body for creating a new workspace."""

    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_max_255(cls, v: str) -> str:
        if len(v) > 255:
            raise ValueError("name must be 255 characters or fewer")
        return v


class WorkspaceUpdate(BaseModel):
    """Request body for updating a workspace (PATCH — all fields optional)."""

    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_max_255(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 255:
            raise ValueError("name must be 255 characters or fewer")
        return v


class MemberRoleUpdate(BaseModel):
    """Request body for updating a workspace member's role."""

    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        return _validate_role(v)


class EmailInviteCreate(BaseModel):
    """Request body for creating an email invite."""

    email: EmailStr
    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        return _validate_role(v)


class LinkInviteCreate(BaseModel):
    """Request body for creating a shareable link invite."""

    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        return _validate_role(v)


class InviteAccept(BaseModel):
    """Request body for accepting an invite via token."""

    token: str


class CreditPoolAllocate(BaseModel):
    """Request body for allocating credits from org balance to a workspace pool."""

    amount: int

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount must be greater than 0")
        return v


class WorkspaceResponse(BaseModel):
    """Response schema for a workspace."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    is_active: bool
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    member_count: int = 0
    pool_allocated: int | None = None
    pool_used: int | None = None


class WorkspaceMemberResponse(BaseModel):
    """Response schema for a workspace member."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    user_name: str
    user_email: str
    role: str
    joined_at: datetime
    invited_by: str | None = None


class InviteResponse(BaseModel):
    """Response schema for a workspace invite (email or link, without plaintext token)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    role: str
    method: str
    invitee_email: str | None = None
    created_at: datetime
    expires_at: datetime
    is_revoked: bool


class LinkInviteResponse(BaseModel):
    """Response schema returned only at link invite creation (contains plaintext token path)."""

    invite_url: str
    expires_at: datetime


class AuditLogResponse(BaseModel):
    """Response schema for an audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str | None = None
    actor_id: str
    actor_name: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime

    @classmethod
    def from_orm_log(cls, log: Any) -> "AuditLogResponse":
        """Build response from AuditLog ORM object (handles log_metadata → metadata rename)."""
        return cls(
            id=log.id,
            workspace_id=log.workspace_id,
            actor_id=log.actor_id,
            actor_name=log.actor_name,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            target_name=log.target_name,
            before_state=log.before_state,
            after_state=log.after_state,
            metadata=log.log_metadata,
            created_at=log.created_at,
        )


class CreditPoolResponse(BaseModel):
    """Response schema for a workspace credit pool."""

    model_config = ConfigDict(from_attributes=True)

    workspace_id: str
    allocated_credits: int
    used_credits: int
    available_credits: int
    last_alert_threshold: int | None = None
    updated_at: datetime

    @classmethod
    def from_pool(cls, pool: Any) -> "CreditPoolResponse":
        """Build response from WorkspaceCreditPool ORM object with computed available."""
        return cls(
            workspace_id=pool.workspace_id,
            allocated_credits=pool.allocated_credits,
            used_credits=pool.used_credits,
            available_credits=pool.allocated_credits - pool.used_credits,
            last_alert_threshold=pool.last_alert_threshold,
            updated_at=pool.updated_at,
        )
