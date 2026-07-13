"""User favorites and recent models."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class UserFavorite(Base):
    """User favorite optimization models."""

    __tablename__ = "user_favorites"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # P1.5 fusion: favorites are keyed on the unified Model (model_project_id). The legacy
    # model_id is now nullable (new rows omit it) and drops in the contract release.
    model_id = Column(String, ForeignKey("model_catalog.id", ondelete="CASCADE"), nullable=True)
    model_project_id = Column(
        String, ForeignKey("model_projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    user = relationship("User", backref="favorites")
    model = relationship("ModelCatalog", backref="favorited_by")

    __table_args__ = (
        Index("uq_user_project_favorite", "user_id", "model_project_id", unique=True),
    )


class RecentModel(Base):
    """Recently viewed/used models by user."""

    __tablename__ = "recent_models"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # P1.5 fusion: recents are keyed on the unified Model (model_project_id). The legacy
    # model_id is now nullable (new rows omit it) and drops in the contract release.
    model_id = Column(String, ForeignKey("model_catalog.id", ondelete="CASCADE"), nullable=True)
    model_project_id = Column(
        String, ForeignKey("model_projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    last_accessed = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    access_count = Column(String, default="1")

    # Relationships
    user = relationship("User", backref="recent_models")
    model = relationship("ModelCatalog", backref="recently_viewed_by")

    __table_args__ = (Index("uq_user_project_recent", "user_id", "model_project_id", unique=True),)
