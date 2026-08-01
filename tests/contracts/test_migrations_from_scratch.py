"""The migration chain must run clean on an empty database.

# CONTRACT-TEST: a fresh install migrates to head without manual steps.

This replaces ``test_p15_backfill.py``, whose subject D-26 removed: that test
drove the P1.5 fusion backfill over ``model_catalog`` / ``organization_models``
rows, and those tables no longer exist. The backfill migration itself is still in
the chain — a new install runs it, finds nothing to move, and moves on — so what
needs guarding is no longer "does the backfill map every legacy row" but "does
the whole chain still apply to a database that starts empty".

That is the property a self-hosted operator depends on and the one most likely to
break silently: a migration that assumes a table an earlier migration dropped
fails only on a fresh install, never on the developer database that has been
upgraded step by step.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text

from tests.conftest import terminate_backends

pytestmark = pytest.mark.contract

_SCRATCH_DB = "jaot_migration_scratch"

# Tables D-26 removed. If one of these comes back, some migration is recreating
# schema the contract release deleted.
_RETIRED_TABLES = {"model_catalog", "organization_models"}

# A representative slice of what a usable install needs on disk.
_REQUIRED_TABLES = {
    "alembic_version",
    "organizations",
    "users",
    "api_keys",
    "model_projects",
    "model_project_listings",
    "model_executions",
    "model_reviews",
    "platform_settings",
}


@contextmanager
def _database_url(url: str):
    """Point alembic at ``url`` for the duration of the block.

    ``infra/alembic/env.py`` resolves the connection from ``DATABASE_URL`` in the
    environment and overwrites whatever ``sqlalchemy.url`` the config carries, so
    setting it on the Config object alone silently migrates the *test* database
    instead of the scratch one.
    """
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="module")
def fresh_install(db_engine):
    """An empty database migrated to head, as an Inspector. Built once.

    Module-scoped deliberately: every test here reads schema and none of them
    writes, so running the full chain — 68 migrations — once instead of per test
    is the same assertion for a quarter of the work.
    """
    admin = create_engine(db_engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}"'))
        conn.execute(text(f'CREATE DATABASE "{_SCRATCH_DB}"'))

    url = db_engine.url.set(database=_SCRATCH_DB)
    # render_as_string(hide_password=False), not str(): SQLAlchemy masks the
    # password as "***" in the plain string form, which reaches Postgres as a
    # literal wrong password.
    dsn = url.render_as_string(hide_password=False)

    engine = None
    try:
        with _database_url(dsn):
            cfg = AlembicConfig("infra/alembic.ini")
            cfg.set_main_option("sqlalchemy.url", dsn)
            command.upgrade(cfg, "head")

        engine = create_engine(url)
        yield inspect(engine)
    finally:
        if engine is not None:
            engine.dispose()
        terminate_backends(admin, _SCRATCH_DB)
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}"'))
        admin.dispose()


def test_chain_applies_to_an_empty_database(fresh_install):
    """Every migration, in order, against a database that starts with nothing.

    The fixture raises if any migration in the chain fails, so reaching this
    body already proves the chain applies; what is asserted here is that it
    produced a usable schema rather than an empty one.
    """
    tables = set(fresh_install.get_table_names())

    missing = _REQUIRED_TABLES - tables
    assert not missing, f"a fresh install is missing tables: {sorted(missing)}"

    resurrected = _RETIRED_TABLES & tables
    assert not resurrected, (
        f"tables removed by the contract release came back: {sorted(resurrected)}"
    )


def test_fresh_install_schema_matches_the_orm(fresh_install):
    """The columns the ORM declares exist, for the models D-26 reshaped.

    A fresh install that migrates without error can still be wrong: a migration
    that drops a column the ORM still maps only fails at the first query.
    """
    from app.models.favorite import RecentModel, UserFavorite
    from app.models.optimization_model import ModelExecution, ModelReview

    for model in (RecentModel, UserFavorite, ModelReview, ModelExecution):
        actual = {c["name"] for c in fresh_install.get_columns(model.__tablename__)}
        declared = {c.name for c in model.__table__.columns}
        missing = declared - actual
        assert not missing, (
            f"{model.__name__} maps columns a fresh install does not have: {sorted(missing)}"
        )


def test_access_count_is_an_integer_on_a_fresh_install(fresh_install):
    """D-26 turned a number-stored-as-text into a real integer."""
    column = next(
        c for c in fresh_install.get_columns("recent_models") if c["name"] == "access_count"
    )

    assert "INTEGER" in str(column["type"]).upper(), (
        f"access_count is {column['type']}, not an integer"
    )


def test_one_review_per_user_per_model_is_enforced_by_the_database(fresh_install):
    """The unique index the fusion had silently defused (D-26).

    The old index was UNIQUE on (user_id, catalog_id); every post-fusion review
    leaves catalog_id NULL, and Postgres does not treat NULLs as equal, so it
    admitted unlimited duplicates.
    """
    indexes = fresh_install.get_indexes("model_reviews")

    unique_on = {tuple(i["column_names"]) for i in indexes if i.get("unique") and i["column_names"]}
    assert ("user_id", "model_project_id") in unique_on, (
        f"no unique index on (user_id, model_project_id); found {sorted(unique_on)}"
    )
