"""ModelVersion — point-in-time snapshot of a builder document's canvas."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class ModelVersion(Base):
    """A snapshot of a ModelBuilderDocument's canvas_json at a point in time.

    Two kinds of snapshots exist:
    - Unnamed checkpoints (is_named=False): created automatically on each save.
      Pruned to the most recent 50 per document.
    - Named versions (is_named=True): created explicitly by the user.
      NEVER pruned automatically.

    The ``sequence`` counter is a monotonically increasing integer within a
    document so that versions can be ordered without relying on wall-clock time.
    """

    __tablename__ = "model_version_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_builder_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canvas_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    model_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    change_summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    is_named: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            f"<ModelVersion(id={self.id!r}, document_id={self.document_id!r}, "
            f"sequence={self.sequence}, is_named={self.is_named})>"
        )
