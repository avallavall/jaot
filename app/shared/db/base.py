"""Base class for SQLAlchemy models."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    """Base class for all database models."""


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


# The session annotation endpoints should use (D-18).
#
# **Import it from `app.api.deps`**, which re-exports it — that is the one place
# route modules take dependencies from, and the project rule says so.
#
# It is *defined* here, next to the `get_db` it wraps, only because `app.api.deps`
# also builds `CurrentUser` on top of `app.api.v2.auth`, and `auth` needs a session
# annotation of its own. Defining the alias in `deps` made that a cycle:
# deps -> auth -> deps. Here it depends on nothing but `get_db`, so `auth` can
# import it directly and everything downstream still goes through `deps`.
DBSession = Annotated[Session, Depends(get_db)]
