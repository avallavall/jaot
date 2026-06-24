"""Database initialization script."""

import logging

from app.models import (  # noqa: F401
    APIKey,
    CreditTransaction,
    ExchangeRate,
    ModelCatalog,
    ModelExecution,
    Organization,
    OrganizationModel,
    UsageRecord,
    User,
    Withdrawal,
    WithdrawalSchedule,
)
from app.shared.db.base import Base
from app.shared.db.session import engine

logger = logging.getLogger(__name__)


def init_database() -> None:
    """Create all database tables."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created successfully")
    except Exception as e:
        logger.error(f"✗ Failed to create database tables: {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_database()
