"""SQLAlchemy query helper utilities."""

from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import asc, desc
from sqlalchemy.orm import Query, Session

T = TypeVar("T")


def get_or_404(
    db: Session, model: type[T], id: str, id_field: str = "id", error_message: str | None = None
) -> T:
    """Get a model instance by ID or raise 404.

    Args:
        db: Database session
        model: SQLAlchemy model class
        id: ID value to search for
        id_field: Name of the ID field (default: "id")
        error_message: Custom error message

    Returns:
        Model instance

    Raises:
        HTTPException: 404 if not found

    Examples:
        >>> user = get_or_404(db, User, "user_123")
        >>> org = get_or_404(db, Organization, "org_456", error_message="Org not found")
    """
    field = getattr(model, id_field)
    instance = db.query(model).filter(field == id).first()

    if not instance:
        message = error_message or f"{model.__name__} not found"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)

    return instance


def get_or_none(db: Session, model: type[T], id: str, id_field: str = "id") -> T | None:
    """Get a model instance by ID or return None.

    Args:
        db: Database session
        model: SQLAlchemy model class
        id: ID value to search for
        id_field: Name of the ID field (default: "id")

    Returns:
        Model instance or None
    """
    field = getattr(model, id_field)
    return db.query(model).filter(field == id).first()


def apply_sorting(
    query: Query[Any],
    model: type[T],
    sort_by: str = "created_at",
    sort_order: str = "desc",
    *,
    allowed_fields: list[str],
) -> Query[Any]:
    """Apply sorting to a query.

    Args:
        query: SQLAlchemy query
        model: Model class for field validation
        sort_by: Field to sort by
        sort_order: "asc" or "desc"
        allowed_fields: List of allowed sort fields (required for SQL injection prevention)

    Returns:
        Query with sorting applied

    Examples:
        >>> query = apply_sorting(query, User, "name", "asc", allowed_fields=["name", "created_at"])
        >>> query = apply_sorting(query, Model, "created_at", "desc", allowed_fields=["name", "created_at"])
    """
    if sort_by not in allowed_fields:
        sort_by = "created_at"  # Default fallback

    if not hasattr(model, sort_by):
        sort_by = "created_at"

    field = getattr(model, sort_by)

    if sort_order.lower() == "asc":
        return query.order_by(asc(field))
    else:
        return query.order_by(desc(field))


def apply_search(
    query: Query[Any], model: type[T], search_term: str, search_fields: list[str]
) -> Query[Any]:
    """Apply search filter to a query.

    Args:
        query: SQLAlchemy query
        model: Model class
        search_term: Search term
        search_fields: List of fields to search in

    Returns:
        Query with search filter applied

    Examples:
        >>> query = apply_search(query, User, "john", ["name", "email"])
    """
    if not search_term:
        return query

    from sqlalchemy import or_

    search_pattern = f"%{search_term}%"
    conditions = []

    for field_name in search_fields:
        if hasattr(model, field_name):
            field = getattr(model, field_name)
            conditions.append(field.ilike(search_pattern))

    if conditions:
        query = query.filter(or_(*conditions))

    return query


def apply_filters(query: Query[Any], model: type[T], filters: dict[str, Any]) -> Query[Any]:
    """Apply multiple equality filters to a query.

    Args:
        query: SQLAlchemy query
        model: Model class
        filters: Dict of field_name -> value (None values are skipped)

    Returns:
        Query with filters applied

    Examples:
        >>> query = apply_filters(query, User, {"is_active": True, "plan": "pro"})
    """
    for field_name, value in filters.items():
        if value is None:
            continue
        if hasattr(model, field_name):
            field = getattr(model, field_name)
            query = query.filter(field == value)

    return query


def exists(db: Session, model: type[T], **filters: Any) -> bool:
    """Check if a record exists.

    Args:
        db: Database session
        model: Model class
        **filters: Field filters

    Returns:
        True if exists, False otherwise

    Examples:
        >>> if exists(db, User, email="test@example.com"):
        ...     raise HTTPException(400, "Email already exists")
    """
    query = db.query(model)
    for field_name, value in filters.items():
        if hasattr(model, field_name):
            field = getattr(model, field_name)
            query = query.filter(field == value)
    return query.first() is not None
