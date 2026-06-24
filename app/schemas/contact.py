"""Pydantic v2 schemas for the public contact form endpoint (Phase 9)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ContactCreate(BaseModel):
    """Request body for POST /api/v2/contact.

    Fields:
    - name/email/subject/message: the 4 visible form fields (D-05).
      Length bounds use ``Field(min_length=..., max_length=...)`` so Pydantic
      emits idiomatic 422 errors with field locations on violation.
    - website: HONEYPOT (D-01). Bots fill it; humans never see it.
      No length constraint — we WANT spammers to drop whatever they want here
      and learn nothing from any 422 about how long the field can be.
      The handler rejects with 400 on any non-empty value.
    - locale: visitor's UI locale code (D-09). Stored verbatim for the email
      body's `Locale: <code>` header line. Bounded to 8 chars (e.g. "es-ES").

    T-09-03 (reply-to header injection): EmailStr validates address shape at
    the schema layer — malformed values raise 422 before persistence.
    """

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    website: str | None = None  # honeypot — handler enforces, NOT the schema
    locale: str | None = Field(default=None, max_length=8)


class ContactResponse(BaseModel):
    """Response body for POST /api/v2/contact.

    Echoes ONLY the persisted-row id, status, and created_at — never the
    user-supplied name/email/subject/body (T-09-06: privacy minimum).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    created_at: datetime
