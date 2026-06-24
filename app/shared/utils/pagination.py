"""Pagination models and utilities."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Query

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Common pagination parameters."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"page": 1, "page_size": 20, "sort_by": "created_at", "sort_order": "desc"}
        }
    )

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    sort_by: str = Field(default="created_at", description="Field to sort by")
    sort_order: str = Field(default="desc", description="Sort order (asc or desc)")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [],
                "total": 100,
                "page": 1,
                "page_size": 20,
                "total_pages": 5,
                "has_next": True,
                "has_prev": False,
            }
        }
    )

    items: list[T] = Field(..., description="List of items for current page")
    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether there is a next page")
    has_prev: bool = Field(..., description="Whether there is a previous page")


def paginate_query(query: Query[Any], page: int = 1, page_size: int = 20) -> tuple[list[Any], int]:
    """
    Paginate a SQLAlchemy query.

    Args:
        query: SQLAlchemy query object
        page: Page number (1-indexed)
        page_size: Number of items per page

    Returns:
        Tuple of (items for current page, total count)
    """
    total = query.count()

    offset = (page - 1) * page_size

    items = query.offset(offset).limit(page_size).all()

    return items, total


def create_paginated_response(
    items: list[T], total: int, page: int, page_size: int
) -> dict[str, Any]:
    """
    Create a paginated response dictionary.

    Args:
        items: List of items for current page
        total: Total number of items
        page: Current page number
        page_size: Items per page

    Returns:
        Dictionary with pagination metadata
    """
    total_pages = (total + page_size - 1) // page_size  # Ceiling division

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
