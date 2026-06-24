"""AuditLog model for tracking user actions across workspaces and organizations."""

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class AuditAction(str, Enum):
    """Actions that are recorded in the audit log."""

    SOLVE = "solve"
    MODEL_EDIT = "model_edit"
    MODEL_DELETE = "model_delete"
    MEMBER_INVITE = "member_invite"
    MEMBER_REMOVE = "member_remove"
    ROLE_CHANGE = "role_change"
    POOL_ALLOCATE = "pool_allocate"
    WORKSPACE_CREATE = "workspace_create"
    WORKSPACE_UPDATE = "workspace_update"
    TRIGGER_CREATE = "trigger_create"
    TRIGGER_UPDATE = "trigger_update"
    TRIGGER_DELETE = "trigger_delete"
    TRIGGER_FIRE = "trigger_fire"
    TRIGGER_SCHEDULE_CREATE = "trigger_schedule_create"
    TRIGGER_SCHEDULE_UPDATE = "trigger_schedule_update"
    TRIGGER_SCHEDULE_DELETE = "trigger_schedule_delete"
    # Seller experience actions
    VERIFICATION_APPROVE = "verification_approve"
    VERIFICATION_REJECT = "verification_reject"
    PLACEMENT_REVOKE = "placement_revoke"
    # D-09: 5 SOLVER_LICENSE_* values removed (BYOL → platform license).
    # DB rows deleted by infra/alembic/versions/20260424c_phase74_byol_teardown.


class AuditLog(Base):
    """Immutable record of a user action for compliance and visibility.

    Design notes:
    - actor_name and target_name are denormalized snapshots so the log remains
      readable even after users or targets are deleted.
    - before_state / after_state hold JSON snapshots for edit/delete actions.
    - metadata holds extra context (credit amount, error message, etc.).
    - log_action() in audit_service.py writes entries via db.add() only —
      the calling route handler commits to keep the log atomic with the action.
    - Visible to workspace admins and org owner only.
    - 1-year retention enforced by a Celery Beat cleanup task.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        # Composite index for time-range queries scoped to an organization
        Index("ix_audit_logs_org_created_at", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # nullable: org-level actions (e.g., org settings change) have no workspace
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # User who performed the action
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Denormalized snapshot — readable even if the user account is later deleted
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # "model", "user", "workspace", "credits", etc.
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Denormalized snapshot of the target name
    target_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # JSON snapshots for edit/delete actions
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Extra context: credit amount, solve params, etc.
    # Named log_metadata to avoid conflict with SQLAlchemy's reserved "metadata" attribute.
    log_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    # Cross-reference fields (D-7.1-12). Nullable — only set when the audit
    # entry is tied to a specific entity (e.g. SolverLicense). Partial index
    # idx_audit_logs_reference speeds up (reference_type, reference_id) queries.
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id!r}, action={self.action!r}, "
            f"actor_id={self.actor_id!r}, organization_id={self.organization_id!r})>"
        )
