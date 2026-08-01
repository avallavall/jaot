"""Database session management - PostgreSQL only."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import settings

DATABASE_URL = settings.DATABASE_URL


def build_engine(database_url: str | None = None) -> Engine:
    """Build the application engine from settings.

    A function rather than a bare module-level call so the pool configuration
    can be asserted on: the test harness swaps the module-level ``engine`` for
    its own (different pool, no timeout), so reading that global tells you
    nothing about what production is configured to do.
    """
    return create_engine(
        database_url if database_url is not None else DATABASE_URL,
        poolclass=QueuePool,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        # D-25: explicit, and much shorter than SQLAlchemy's 30s default. A
        # request that cannot get a connection should fail while the caller is
        # still listening, not occupy a thread for half a minute and then 500.
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE,
        echo=False,  # Set to True for SQL debugging
        # Anchor the session timezone so naive timestamps (legacy callers, tests)
        # are interpreted as UTC by timestamptz columns regardless of server config.
        connect_args={"options": "-c timezone=utc"},
    ).execution_options(
        # sqlalchemy-celery-beat hardcodes schema='celery_schema' in its models.
        # Map it to None (public schema) so the API can access Beat tables.
        schema_translate_map={"celery_schema": None},
    )


# PostgreSQL configuration (development & production)
engine = build_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
