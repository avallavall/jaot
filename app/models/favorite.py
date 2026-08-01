"""User favorites and recent models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class UserFavorite(Base):
    """User favorite optimization models."""

    __tablename__ = "user_favorites"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # P1.5 fusion: favorites are keyed on the unified Model.
    model_project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("model_projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Relationships
    user = relationship("User", backref="favorites")

    __table_args__ = (
        Index("uq_user_project_favorite", "user_id", "model_project_id", unique=True),
    )


class RecentModel(Base):
    """Recently viewed/used models by user."""

    __tablename__ = "recent_models"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # P1.5 fusion: recents are keyed on the unified Model.
    model_project_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("model_projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    last_accessed: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # Was a number stored as text until D-26; the service had to cast through
    # integer on every increment and the schema converted it on the way out.
    access_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # Relationships
    user = relationship("User", backref="recent_models")

    __table_args__ = (Index("uq_user_project_recent", "user_id", "model_project_id", unique=True),)
