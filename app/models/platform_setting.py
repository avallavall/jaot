"""Platform settings model for runtime admin configuration."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class PlatformSetting(Base):
    """Key-value store for platform-wide runtime settings.

    Used for admin-configurable values like commission rates,
    feature flags, and other platform parameters.
    """

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    # Text, not String(500): JSON-typed settings (the per-model LLM pricing map)
    # outgrew it, and a 500-char ceiling silently turns "add one more entry" into
    # a failed seed on fresh installs.
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<PlatformSetting(key={self.key}, value={self.value})>"
