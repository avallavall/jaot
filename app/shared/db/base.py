"""Base class for SQLAlchemy models."""

from collections.abc import Generator

from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database sessions.

    Yields:
        Database session
    """
    # Lazy import to avoid circular / eager engine creation
    # (allows Alembic to import Base without connecting to the database)
    from app.shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
