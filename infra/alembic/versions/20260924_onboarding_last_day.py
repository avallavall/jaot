"""Record which onboarding email a user got last.

The emails for days 1, 3 and 14 were queued at signup with a countdown. A
worker holds such a message unacknowledged until it is due, and RabbitMQ
closes a channel that holds one longer than ``consumer_timeout`` (30 minutes
by default). An hourly sweep now sends each email when it is due, and this
column stops it from sending the same one twice.

Existing users are set to 14: their emails were queued the old way, and the
sweep must not send them a second copy.

Additive and reversible: the downgrade drops the column.

Revision ID: 20260924_onboarding_last_day
Revises: 20260924_llm_retained_spend
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_onboarding_last_day"
down_revision = "20260924_llm_retained_spend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarding_last_day", sa.Integer(), nullable=True))
    op.execute("UPDATE users SET onboarding_last_day = 14")


def downgrade() -> None:
    op.drop_column("users", "onboarding_last_day")
