"""LLM conversation and message models for natural language formulation."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _default_conv_id() -> str:
    return generate_id("conv_")


def _default_msg_id() -> str:
    return generate_id("msg_")


_DEFAULT_TTL_HOURS = 24


def _default_expires_at() -> datetime:
    """Default expiry: utcnow + 24h.

    Callers with a DB session should compute expires_at explicitly using
    PlatformSettingsService.get_int(db, "LLM_CONVERSATION_TTL_HOURS")
    and pass it when constructing LLMConversation.
    """
    return utcnow() + timedelta(hours=_DEFAULT_TTL_HOURS)


class LLMConversation(Base):
    """A conversation thread for LLM-powered formulation generation.

    Each conversation belongs to an organization/user pair and may optionally
    be linked to an OrganizationModel once the user accepts the formulation.
    Conversations auto-expire after a configurable TTL (default 24h).
    """

    __tablename__ = "llm_conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_default_conv_id)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=False, index=True
    )
    organization_model_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organization_models.id"), nullable=True
    )

    # Current formulation state (latest structured output from LLM)
    current_formulation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Template that started this conversation (if any)
    template_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Builder document ID for conversation scoping (no FK — ephemeral conversations)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, default=_default_expires_at, nullable=False, index=True
    )

    # Relationships
    messages: Mapped[list["LLMMessage"]] = relationship(
        "LLMMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="LLMMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<LLMConversation(id={self.id}, org={self.organization_id})>"


class LLMMessage(Base):
    """A single message in an LLM conversation.

    Messages have a role (user/assistant/system) and may optionally include
    a structured formulation JSON (for assistant messages that produced one).
    """

    __tablename__ = "llm_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_default_msg_id)
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("llm_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured formulation output (assistant messages only)
    formulation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Real Anthropic token usage + cost for assistant messages (W17).
    # Captured from the API response (streaming: message_start/message_delta
    # usage; non-streaming: response.usage) and priced via the
    # LLM_MODEL_PRICING_EUR_PER_MTOK platform setting. Nullable — user
    # messages and rows persisted before the migration carry NULL.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    # Relationships
    conversation: Mapped["LLMConversation"] = relationship(
        "LLMConversation", back_populates="messages"
    )

    __table_args__ = (Index("ix_llm_messages_conv_created", "conversation_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<LLMMessage(id={self.id}, role={self.role})>"
