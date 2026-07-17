"""Convert all timestamp columns to timestamptz (ADR-007 S6).

Stored values have always been UTC wall-clock (``utcnow()`` is timezone-aware
UTC; the naive columns simply dropped the offset on write). Interpreting them
as UTC during the type change is therefore lossless.

Excluded: ``celery_*`` tables (owned by sqlalchemy-celery-beat — its models
define their own column types) and ``alembic_version``.

Revision ID: 20260710_timestamptz
Revises: 20260703_execution_dataset
Create Date: 2026-07-10
"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "20260710_timestamptz"
down_revision = "20260703_execution_dataset"
branch_labels = None
depends_on = None

_SELECT_COLUMNS = """
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = 'public'
      AND t.table_type = 'BASE TABLE'
      AND c.data_type = :data_type
      AND c.table_name NOT LIKE 'celery\\_%'
      AND c.table_name <> 'alembic_version'
    ORDER BY c.table_name, c.ordinal_position
"""


def _alter_all(from_type: str, to_type: str) -> None:
    conn = op.get_bind()
    rows = conn.execute(text(_SELECT_COLUMNS), {"data_type": from_type}).fetchall()
    for table, column in rows:
        # AT TIME ZONE 'UTC' converts naive->aware (upgrade) and aware->naive
        # (downgrade) interpreting/rendering the value as UTC in both directions.
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
            f"TYPE {to_type} USING \"{column}\" AT TIME ZONE 'UTC'"
        )


def upgrade() -> None:
    _alter_all("timestamp without time zone", "TIMESTAMP WITH TIME ZONE")


def downgrade() -> None:
    _alter_all("timestamp with time zone", "TIMESTAMP WITHOUT TIME ZONE")
