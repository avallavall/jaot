"""Common schemas used across multiple endpoints."""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

# Generic type for paginated responses
T = TypeVar("T")


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
