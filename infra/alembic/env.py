"""
Alembic environment configuration for JAOT.

Reads DATABASE_URL from environment (or .env via dotenv).
Imports all models so autogenerate can detect schema changes.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# env.py is at infra/alembic/env.py — up 3 levels to project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# override=False preserves env vars already set (e.g. by conftest.py).
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

# Resolve DATABASE_URL BEFORE importing app modules.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jaot:jaot@localhost:5432/jaot_dev")

# Base no longer eagerly imports session.py, so this is safe with the DB down.
from app.shared.db.base import Base

from app.models import (  # noqa: F401
    APIKey,
    CreditTransaction,
    ExchangeRate,
    FeaturedPlacement,
    ModelViewEvent,
    Notification,
    NotificationPreference,
    Organization,
    PlatformSetting,
    SellerToSAcceptance,
    UsageRecord,
    User,
    ModelCatalog,
    OrganizationModel,
    ModelExecution,
    ModelReview,
    VerificationRequest,
    Withdrawal,
    WithdrawalSchedule,
    UserFavorite,
    RecentModel,
    Workspace,
    WorkspaceMember,
    WorkspaceInvite,
    AuditLog,
    WorkspaceCreditPool,
    LLMConversation,
    LLMMessage,
)

config = context.config

# disable_existing_loggers=False preserves loggers imported before this call
# (e.g. app.* at pytest collection time); fileConfig would otherwise silence
# them for the rest of the test session.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    Useful for generating migration SQL for review before applying.

    Usage:
        alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Connects to the database and applies migrations directly.

    Usage:
        alembic upgrade head
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # Existing batch-mode migrations still work; new migrations use
            # native PostgreSQL DDL.
            render_as_batch=False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
