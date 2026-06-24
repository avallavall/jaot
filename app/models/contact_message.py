"""ContactMessage model — public contact form submissions (Phase 9).

Implements:
- D-03: durable DB trail before async email send
- D-05: 4 visible fields stored (name, email, subject, message → body)
- D-06: nullable user_id/organization_id (anonymous-friendly; NO FK constraints)
- D-07: no recipient column — PSS-driven at task time (CONTACT_RECIPIENT)
- D-09: locale column stored verbatim so the email body can include `Locale: <code>`

Schema mirrors infra/alembic/versions/20260516_add_contact_messages.py exactly.
No relationships defined: anonymous submissions must not cascade against users
or organizations, so user_id/organization_id are unindexed nullable strings
(tag-only, never used as a retrieval filter in this phase).
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class ContactMessage(Base):
    """Durable record of a single public contact-form submission.

    Lifecycle:
    - Created with status="pending" by POST /api/v2/contact handler.
    - send_contact_email Celery task reads the row, sends the email,
      then flips status to "sent" (with sent_at) or "failed" (with last_error).
    - attempts counter is incremented on every send attempt.

    Columns:
    - id: prefixed with "ctc_"
    - name/email/subject/body: the 4 visible form fields (D-05)
    - locale: visitor's UI locale at submission time (D-09)
    - user_id/organization_id: optional auto-tag when signed-in (D-06).
      Nullable. NO FK — anonymous-friendly per D-06.
    - ip_address: client IP captured server-side for abuse triage
    - status: "pending" | "sent" | "failed" (inline string enum per PATTERNS analog)
    - attempts: incremented on every send_contact_email invocation
    - last_error: last exception type+message (bounded length); NULL on success
    - sent_at: UTC timestamp set when status flips to "sent"
    """

    __tablename__ = "contact_messages"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("ctc_")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (Index("ix_contact_messages_status_created", "status", "created_at"),)

    def __repr__(self) -> str:
        return f"<ContactMessage(id={self.id!r}, status={self.status!r}, attempts={self.attempts})>"
