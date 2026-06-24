"""ModelBuilderDocument — persists visual model builder canvas state."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class ModelBuilderDocument(Base):
    """Stores the canvas and serialized model for a visual model builder session.

    Two separate JSON fields are maintained deliberately:
    - canvas_json: React Flow graph state (nodes, edges, viewport)
    - model_json: Last serialized OptimizationProblem sent to the solver

    These fields must never be conflated — canvas state and problem state
    have different lifecycles and update independently.
    """

    __tablename__ = "model_builder_documents"

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
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="Untitled Model",
    )

    # React Flow canvas state — nodes, edges, viewport
    canvas_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Last serialized OptimizationProblem (None until first export)
    model_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return f"<ModelBuilderDocument(id={self.id!r}, name={self.name!r})>"
