"""Database helper functions to reduce code duplication."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import APIKey, Organization, User


def get_organization_or_404(db: Session, organization_id: str) -> Organization:
    """Get organization or raise 404.

    Args:
        db: Database session
        organization_id: Organization ID

    Returns:
        Organization model

    Raises:
        HTTPException: 404 if organization not found
    """
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {organization_id} not found",
        )
    return org


def get_organization_or_none(db: Session, organization_id: str) -> Organization | None:
    """Get organization or return None.

    Args:
        db: Database session
        organization_id: Organization ID

    Returns:
        Organization model or None
    """
    return db.query(Organization).filter(Organization.id == organization_id).first()


def get_user_or_none(db: Session, user_id: str) -> User | None:
    """Get user or return None.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        User model or None
    """
    return db.query(User).filter(User.id == user_id).first()


def get_api_key_by_hash(db: Session, key_hash: str) -> APIKey | None:
    """Get API key by hash.

    Args:
        db: Database session
        key_hash: Key hash to look up

    Returns:
        APIKey model or None
    """
    return db.query(APIKey).filter(APIKey.key_hash == key_hash).first()
