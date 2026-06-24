"""WorkspaceCreditPool model — per-workspace credit budget drawn from org balance."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class WorkspaceCreditPool(Base):
    """A credit budget allocated to a specific workspace.

    Design notes:
    - One pool per workspace (1:1 enforced by unique constraint on workspace_id).
    - Credits are one-directional: drawn from Organization.credits_balance into
      the pool via admin allocation; no inter-pool transfers.
    - When a solve is initiated in a workspace context:
        1. Deduct from pool if pool has available credits (atomic UPDATE WHERE).
        2. If pool is exhausted or missing, fall back to org.credits_balance.
    - Threshold alerts fire at 70%, 75%, 80%, 85%, 90%, 95%, 100% usage.
      last_alert_threshold records the last % threshold already notified so
      alerts are not repeated. Reset to None when credits are added to the pool.
    - available_credits = allocated_credits - used_credits (computed in app layer).
    """

    __tablename__ = "workspace_credit_pools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
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
    allocated_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Last usage-percentage threshold for which workspace admins were notified.
    # Prevents repeat alerts for the same threshold crossing.
    last_alert_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        available = self.allocated_credits - self.used_credits
        return (
            f"<WorkspaceCreditPool(id={self.id!r}, workspace_id={self.workspace_id!r}, "
            f"allocated={self.allocated_credits}, used={self.used_credits}, "
            f"available={available})>"
        )
