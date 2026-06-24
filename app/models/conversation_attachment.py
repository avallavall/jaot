"""Conversation attachment model for document uploads."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _default_att_id() -> str:
    return generate_id("att_")


class ConversationAttachment(Base):
    """A document attached to an LLM conversation.

    Stores extracted text from uploaded documents (PDF, CSV, TXT).
    Raw binary is discarded after extraction -- only text is retained.
    """

    __tablename__ = "conversation_attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_default_att_id)
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("llm_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    preview: Mapped[str] = mapped_column(String(250), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<ConversationAttachment(id={self.id}, file={self.filename})>"
