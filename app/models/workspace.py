"""Workspace, WorkspaceMember, WorkspaceInvite models for team collaboration."""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class WorkspaceRole(str, Enum):
    """Per-workspace role assigned to a WorkspaceMember.

    Note: "owner" is NOT a workspace role — it is org-level, stored on
    Organization.owner_user_id. The owner bypasses all workspace-level
    permission checks without needing a WorkspaceMember row.
    """

    ADMIN = "admin"
    EDITOR = "editor"
    SOLVER = "solver"
    VIEWER = "viewer"


class InviteMethod(str, Enum):
    """Method used to invite a user to a workspace."""

    EMAIL = "email"
    LINK = "link"


class Workspace(Base):
    """A workspace — a named sub-namespace within an organization.

    Workspaces let teams group documents, models, and executions together.
    One org can have many workspaces; each workspace has its own member list
    and optional credit pool.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<Workspace(id={self.id!r}, name={self.name!r}, "
            f"organization_id={self.organization_id!r}, is_active={self.is_active})>"
        )


class WorkspaceMember(Base):
    """Join table linking a User to a Workspace with a specific role.

    A user can belong to multiple workspaces (potentially with different roles
    in each). UniqueConstraint on (workspace_id, user_id) prevents duplicate rows.
    """

    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    invited_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            f"<WorkspaceMember(id={self.id!r}, workspace_id={self.workspace_id!r}, "
            f"user_id={self.user_id!r}, role={self.role!r})>"
        )


class WorkspaceInvite(Base):
    """An invitation to join a workspace (email-specific or shareable link).

    Token security:
    - token_hash stores SHA-256(plaintext_token) — plaintext never stored.
    - Accept endpoint validates by hashing the provided token and comparing hashes.
    - Email invites have invitee_email set and are single-use (accepted_at set).
    - Link invites have invitee_email=None and can be accepted by multiple people.
    """

    __tablename__ = "workspace_invites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    invitee_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<WorkspaceInvite(id={self.id!r}, workspace_id={self.workspace_id!r}, "
            f"method={self.method!r}, is_revoked={self.is_revoked})>"
        )
