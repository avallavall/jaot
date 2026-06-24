"""Tests for Organization owner_user_id FK constraint.

These tests require a running PostgreSQL database with migrations applied.
"""

from sqlalchemy import inspect


def test_owner_user_id_fk_exists(db_session):
    """The organizations table should have a FK on owner_user_id -> users.id."""
    inspector = inspect(db_session.bind)
    fks = inspector.get_foreign_keys("organizations")
    owner_fk = [fk for fk in fks if fk["constrained_columns"] == ["owner_user_id"]]
    assert len(owner_fk) == 1, f"Expected 1 FK on owner_user_id, found {len(owner_fk)}"
    assert owner_fk[0]["referred_table"] == "users"
    assert owner_fk[0]["referred_columns"] == ["id"]


def test_owner_user_id_fk_has_set_null(db_session):
    """Deleting a user should SET NULL on organization owner_user_id, not cascade delete."""
    from sqlalchemy import text

    from app.models import Organization, User

    # Create org using ORM (handles all defaults)
    org = Organization(id="org_fk_test", name="FK Test Org")
    db_session.add(org)
    db_session.flush()

    # Create user
    user = User(
        id="user_fk_test",
        email="fk@test.com",
        name="FK User",
        organization_id="org_fk_test",
    )
    db_session.add(user)
    db_session.flush()

    # Set owner
    org.owner_user_id = "user_fk_test"
    db_session.commit()

    # Delete user via raw SQL to trigger FK ON DELETE SET NULL
    db_session.execute(text("DELETE FROM users WHERE id = 'user_fk_test'"))
    db_session.commit()

    # Verify owner is now NULL (not cascade-deleted org)
    db_session.expire_all()
    result = db_session.execute(
        text("SELECT owner_user_id FROM organizations WHERE id = 'org_fk_test'")
    )
    row = result.fetchone()
    assert row is not None, "Organization should still exist after user deletion"
    assert row[0] is None, "owner_user_id should be NULL after user deletion"
