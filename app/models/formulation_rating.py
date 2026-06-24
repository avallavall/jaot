"""FormulationRating model for LLM formulation quality feedback."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _default_frt_id() -> str:
    return generate_id("frt_")


class FormulationRating(Base):
    """A thumbs-up/down rating on an LLM conversation formulation.

    Each user can rate a conversation once. Re-rating overwrites the
    previous rating (enforced by UniqueConstraint on conversation_id + user_id).
    """

    __tablename__ = "formulation_ratings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_default_frt_id)
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("llm_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id"), nullable=False
    )

    rating: Mapped[str] = mapped_column(String(10), nullable=False)  # "up" | "down"
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    zone: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # builder|solver|llm|results|dashboard|models
    formulation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_rating_conv_user"),)

    def __repr__(self) -> str:
        return f"<FormulationRating(id={self.id}, rating={self.rating}, zone={self.zone})>"
