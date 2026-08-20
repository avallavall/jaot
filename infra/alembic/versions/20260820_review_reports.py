"""One row per person per reported review.

A review carried a single ``is_reported`` flag and a single ``report_reason``,
and the endpoint overwrote that reason on every call. So a reviewer could report
their own review, one person could report the same review any number of times,
and when two people reported it the second reason replaced the first. The
moderator saw one sentence and could not tell whose it was, nor how many people
had complained.

Reversible: the down leg drops the table. The flag and the reason on
``model_reviews`` are untouched, so nothing that reads them today changes.

Revision ID: 20260820_review_reports
Revises: 20260818_email_lowercase
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260820_review_reports"
down_revision = "20260818_email_lowercase"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_review_reports",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["model_reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # One voice per person, enforced here rather than by a read-then-write check:
    # two concurrent reports would both pass such a check and both insert.
    op.create_index(
        "ix_model_review_report_unique",
        "model_review_reports",
        ["review_id", "user_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_model_review_reports_review_id"),
        "model_review_reports",
        ["review_id"],
    )
    op.create_index(
        op.f("ix_model_review_reports_user_id"),
        "model_review_reports",
        ["user_id"],
    )
    op.create_index(
        op.f("ix_model_review_reports_organization_id"),
        "model_review_reports",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_review_reports_organization_id"), "model_review_reports")
    op.drop_index(op.f("ix_model_review_reports_user_id"), "model_review_reports")
    op.drop_index(op.f("ix_model_review_reports_review_id"), "model_review_reports")
    op.drop_index("ix_model_review_report_unique", "model_review_reports")
    op.drop_table("model_review_reports")
