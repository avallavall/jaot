"""add model_json to model_version_snapshots

Revision ID: g4h5i6j7k8l9
Revises: a1b2c3d4e5f6
Create Date: 2026-02-23 12:00:00.000000+00:00

Adds model_json (JSON, nullable) column to model_version_snapshots table
and backfills from the parent builder document's model_json.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g4h5i6j7k8l9"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("model_version_snapshots") as batch_op:
        batch_op.add_column(sa.Column("model_json", sa.JSON(), nullable=True))

    # Backfill from parent documents
    op.execute(
        """
        UPDATE model_version_snapshots
        SET model_json = (
            SELECT model_json
            FROM model_builder_documents
            WHERE model_builder_documents.id = model_version_snapshots.document_id
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("model_version_snapshots") as batch_op:
        batch_op.drop_column("model_json")
