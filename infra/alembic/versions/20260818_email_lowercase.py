"""Make an email address mean one account, whatever case it is typed in.

``users.email`` was compared byte for byte by Postgres and normalised nowhere in
the application, so ``user@jaot.io`` and ``USER@jaot.io`` were two accounts in
two organisations. Signup accepted the capitalised form of an address that
already existed, which is enough to take someone else's identity in a product
where the address decides which account you sign into, which organisation you
land in, and whether "this email is already in use" is true.

The schemas now trim and lowercase every address that identifies a person
(``NormalizedEmail`` in ``app/schemas/common.py``). This migration brings the
stored rows in line and stops a non-normalised one ever being written again.

A collision cannot be resolved here. Merging two accounts means deciding which
models, executions and memberships survive, and that is a person's decision, not
a migration's. When one exists the upgrade stops and names the addresses.

Revision ID: 20260818_email_lowercase
Revises: 20260817_lazy_snapshot
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op

revision = "20260818_email_lowercase"
down_revision = "20260817_lazy_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    clashes = conn.exec_driver_sql(
        "SELECT lower(email) AS addr, count(*) AS n, string_agg(email, ', ' ORDER BY email) AS rows "
        "FROM users GROUP BY lower(email) HAVING count(*) > 1"
    ).fetchall()
    if clashes:
        detail = "; ".join(f"{row.addr} <- {row.rows}" for row in clashes)
        raise RuntimeError(
            "Cannot lowercase users.email: these addresses would collide. "
            "Merge or delete the duplicate accounts first, then run this again. "
            f"Collisions: {detail}"
        )

    op.execute("UPDATE users SET email = lower(btrim(email)) WHERE email <> lower(btrim(email))")
    op.execute(
        "UPDATE workspace_invites SET invitee_email = lower(btrim(invitee_email)) "
        "WHERE invitee_email IS NOT NULL AND invitee_email <> lower(btrim(invitee_email))"
    )

    # The unique index on users.email stays a plain btree, so ordinary equality
    # lookups keep using it. This constraint is what makes that index behave as
    # a case-insensitive one: every stored value is already lowercase.
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_email_lowercase "
        "CHECK (email = lower(email) AND email = btrim(email))"
    )


def downgrade() -> None:
    # Only the constraint is reversible. The original capitalisation of an
    # address is not recorded anywhere, so lowercasing is one-way: restoring the
    # container image does not restore the rows. Take a backup before upgrading.
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_email_lowercase")
