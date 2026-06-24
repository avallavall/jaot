"""User favorites and recent models."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class UserFavorite(Base):
    """User favorite optimization models."""

    __tablename__ = "user_favorites"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(String, ForeignKey("model_catalog.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    user = relationship("User", backref="favorites")
    model = relationship("ModelCatalog", backref="favorited_by")

    __table_args__ = (UniqueConstraint("user_id", "model_id", name="uq_user_model_favorite"),)


class RecentModel(Base):
    """Recently viewed/used models by user."""

    __tablename__ = "recent_models"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(String, ForeignKey("model_catalog.id", ondelete="CASCADE"), nullable=False)
    last_accessed = Column(DateTime, default=utcnow, onupdate=utcnow)
    access_count = Column(String, default="1")

    # Relationships
    user = relationship("User", backref="recent_models")
    model = relationship("ModelCatalog", backref="recently_viewed_by")

    __table_args__ = (UniqueConstraint("user_id", "model_id", name="uq_user_model_recent"),)
