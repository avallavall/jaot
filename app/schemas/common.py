"""Common schemas used across multiple endpoints."""

from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr

# Generic type for paginated responses
T = TypeVar("T")


def _normalize_email(value: object) -> object:
    """Trim and lowercase an address before it is validated or stored.

    An email address is this product's identity: it decides which account you
    sign into, which organisation you land in, whether an invitation matches
    and whether signup says the address is taken. Postgres compares strings
    byte for byte, so without this a capitalised address is a different
    account. It was: ``user@jaot.io`` and ``USER@jaot.io`` both existed, in
    different organisations, because signup accepted the second one.

    Non-strings pass through untouched so Pydantic reports the type error.
    """
    if isinstance(value, str):
        return value.strip().lower()
    return value


NormalizedEmail = Annotated[EmailStr, BeforeValidator(_normalize_email)]
"""An ``EmailStr`` that is trimmed and lowercased before validation.

Use this instead of ``EmailStr`` anywhere an address identifies a person:
signing in, signing up, resetting a password, inviting someone, naming an
owner. Addresses that are only ever displayed or replied to may stay plain.
"""


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    model_config = ConfigDict(from_attributes=True)


class SuccessResponse(BaseModel):
    """Generic success response."""

    success: bool = True
    message: str = "Operation completed successfully"


class StatusResponse(BaseModel):
    """Acknowledgement carrying only the outcome verb (``deleted``, ``updated``, ...)."""

    status: str


class ErrorResponse(BaseModel):
    """Generic error response."""

    success: bool = False
    error: str
    detail: str | None = None


class TimestampMixin(BaseModel):
    """Mixin for models with timestamps."""

    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
