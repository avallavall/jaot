"""Immutable audit trail for platform setting changes.

Every change to a platform setting (set or reset) is recorded here.
This is a separate table from the org-scoped AuditLog — platform settings
are global and low-volume, so keeping all history forever is appropriate.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class PlatformSettingAudit(Base):
    """Immutable audit trail for platform setting changes."""

    __tablename__ = "platform_setting_audit"
    __table_args__ = (
        Index("ix_psa_setting_key", "setting_key"),
        Index("ix_psa_changed_at", "changed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    new_value: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # null = reset to default
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return f"<PlatformSettingAudit(id={self.id}, key={self.setting_key}, by={self.changed_by})>"
