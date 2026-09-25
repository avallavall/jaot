"""One name per user: fold ``users.display_name`` into ``users.name``.

"Display Name" on My Profile wrote ``display_name``. The member list, the audit
log, the data export and the session read ``name``, and the public profile read
one or the other depending on the page. A rename showed in one place and not in
the others. From this release the code reads and writes ``name`` only.

This copies every non-blank ``display_name`` into ``name`` (the value the person
chose last, on their profile) and then empties ``display_name``, so the column
holds no second copy of anybody's name.

The column stays for one release. ``deploy.sh`` migrates while the previous API
image is still serving, and that image selects ``users.display_name`` on every
authenticated request. Dropping it here would fail every request during the
deploy. The drop is TECH_DEBT D-37.

Not reversible for the data: the down leg cannot tell which names came from the
profile. It copies ``name`` back into ``display_name``, which is what the older
code shows anyway. The deploy takes a backup before migrating; the signup names
this overwrites are only in that backup.

Revision ID: 20260925_one_user_name
Revises: 20260925_workspace_removals
Create Date: 2026-09-25
"""

from alembic import op

revision = "20260925_one_user_name"
down_revision = "20260925_workspace_removals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET name = btrim(display_name) "
        "WHERE display_name IS NOT NULL AND btrim(display_name) <> ''"
    )
    op.execute("UPDATE users SET display_name = NULL WHERE display_name IS NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE users SET display_name = name")
