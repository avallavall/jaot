"""Tests for API dependencies module.

Tests the centralized dependency injection utilities.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.deps import get_current_admin_user, get_current_organization
from app.models import User


class TestGetCurrentAdminUser:
    """Tests for get_current_admin_user dependency."""

    def test_admin_user_passes(self):
        """Test that admin user passes the check."""
        admin_user = MagicMock(spec=User)
        admin_user.is_admin = True

        result = get_current_admin_user(admin_user)

        assert result == admin_user

    def test_non_admin_user_raises_403(self):
        """Test that non-admin user raises 403 Forbidden."""
        regular_user = MagicMock(spec=User)
        regular_user.is_admin = False

        with pytest.raises(HTTPException) as exc_info:
            get_current_admin_user(regular_user)

        assert exc_info.value.status_code == 403
        assert "Admin access required" in exc_info.value.detail


class TestGetCurrentOrganization:
    """Tests for get_current_organization dependency."""

    def test_organization_not_found_raises_404(self, db_session, test_user):
        """Test that 404 is raised when user's organization_id has no row.

        Uses real DB session and a real fixture-loaded user. We expunge the
        user from the session (so its mutation doesn't trigger autoflush),
        point its organization_id at a non-existent org id, then call the
        dependency directly and assert 404 with the correct detail.

        This proves the dependency actually queries the DB by
        organization_id and raises 404 when the row is missing.
        """
        # Detach the user from the session so we can mutate organization_id
        # without triggering an autoflush that would violate the FK.
        db_session.expunge(test_user)
        test_user.organization_id = "org_does_not_exist_404"

        with pytest.raises(HTTPException) as exc_info:
            get_current_organization(test_user, db_session)

        assert exc_info.value.status_code == 404
        assert "Organization not found" in exc_info.value.detail


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
