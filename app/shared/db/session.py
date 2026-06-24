"""Database session management - PostgreSQL only."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import settings

DATABASE_URL = settings.DATABASE_URL

# PostgreSQL configuration (development & production)
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=settings.DB_POOL_RECYCLE,
    echo=False,  # Set to True for SQL debugging
).execution_options(
    # sqlalchemy-celery-beat hardcodes schema='celery_schema' in its models.
    # Map it to None (public schema) so the API can access Beat tables.
    schema_translate_map={"celery_schema": None},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
