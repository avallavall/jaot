"""SolveTrigger, TriggerRun, and TriggerSchedule — trigger models for async solve runs."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class SolveTrigger(Base):
    """An HTTP event trigger that fires async solve runs when called.

    Each trigger is pinned to a specific model version (version_id).
    The pinned version is protected from deletion via RESTRICT on the FK.

    Authentication for the /fire endpoint is via a per-trigger secret
    stored as a SHA-256 hash (trigger_secret). The plaintext is shown
    only once at creation time.

    The trigger may optionally define an override_schema — a list of
    named fields that callers can pass to customize the solve inputs
    without exposing the full model structure.
    """

    __tablename__ = "solve_triggers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_builder_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[str] = mapped_column(
        String(64),
        # RESTRICT prevents deletion of the pinned version while referenced
        ForeignKey("model_version_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # SHA-256 hash of the plaintext trigger secret
    trigger_secret: Mapped[str] = mapped_column(String(128), nullable=False)
    # Array of {name, type, model_field_path, default, required, description}
    override_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    webhook_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Separate secret for signing outbound webhooks (distinct from trigger_secret)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<SolveTrigger(id={self.id!r}, name={self.name!r}, "
            f"organization_id={self.organization_id!r}, is_enabled={self.is_enabled})>"
        )


class TriggerRun(Base):
    """A single execution run of a SolveTrigger.

    Created when /fire is called. Tracks the full lifecycle from pending
    through running to completed/failed, plus the override inputs so
    runs can be replayed via the /rerun endpoint.

    Status values:
    - pending: Queued but not yet picked up by Celery
    - running: Celery task is actively solving
    - completed: Solve finished successfully
    - failed: Solve errored or timed out
    - timeout: Solve exceeded time limit
    - validation_failed: Override data failed schema validation (no solve queued)
    - skipped_credits: Skipped due to insufficient credits (cron runs)
    - skipped_overlap: Skipped because previous run still in progress (cron runs)
    """

    __tablename__ = "trigger_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trigger_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("solve_triggers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Exact override_data input — stored for /rerun support
    override_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Source of the run: "manual" (API /fire), "cron" (scheduled), "rerun" (/rerun endpoint)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    # FK to ModelExecution if a solve was created
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits_consumed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    webhook_delivered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    webhook_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<TriggerRun(id={self.id!r}, trigger_id={self.trigger_id!r}, status={self.status!r})>"
        )


class TriggerSchedule(Base):
    """A cron schedule attached 1:1 to a SolveTrigger.

    When enabled, Celery Beat fires the associated trigger at each cron tick.
    The beat_task_id references the sqlalchemy-celery-beat PeriodicTask row
    so the schedule can be synced/deleted from Beat's internal tables.
    """

    __tablename__ = "trigger_schedules"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("tsch_")
    )
    trigger_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("solve_triggers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Reference to sqlalchemy-celery-beat's PeriodicTask row
    beat_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<TriggerSchedule(id={self.id!r}, trigger_id={self.trigger_id!r}, "
            f"cron={self.cron_expression!r}, is_enabled={self.is_enabled})>"
        )
