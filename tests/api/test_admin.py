"""
Tests for Admin API endpoints.

These tests verify the admin CRUD functionality:
- Organizations CRUD
- Users CRUD
- API Keys management
- Models management
"""

from app.models import (
    APIKey,
    ModelCategory,
    ModelProjectListing,
    Organization,
    User,
)


class TestAdminOrganizations:
    """Tests for admin organization endpoints."""

    def test_list_organizations(self, admin_client, db_session, test_organization):
        """Test listing organizations."""
        response = admin_client.get("/api/v2/admin/organizations")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert data["total"] >= 1
        # Seeded org must appear in returned items
        item_ids = [o["id"] for o in data["items"]]
        assert test_organization.id in item_ids
        # Computed counts must be integers per the org schema
        seeded = next(o for o in data["items"] if o["id"] == test_organization.id)
        assert isinstance(seeded["user_count"], int)
        assert isinstance(seeded["api_key_count"], int)

    def test_list_organizations_with_search(self, admin_client, db_session, test_organization):
        """Test searching organizations by name."""
        response = admin_client.get(
            f"/api/v2/admin/organizations?search={test_organization.name[:4]}"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        org_names = [o["name"] for o in data["items"]]
        assert any(test_organization.name in name for name in org_names)

    def test_list_organizations_pagination(self, admin_client, db_session, test_organization):
        """Test organization pagination."""
        # Create multiple orgs (5 here + at least the test org → page 1 must be full)
        for i in range(5):
            org = Organization(
                id=f"org_pagination_{i}",
                name=f"Pagination Org {i}",
                is_active=True,
            )
            db_session.add(org)
        db_session.commit()

        response = admin_client.get("/api/v2/admin/organizations?page=1&page_size=3")
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 3
        # Page 1 must be full at exactly page_size, not <=
        assert len(data["items"]) == 3
        assert data["total"] >= 6

    def test_get_organization(self, admin_client, db_session, test_organization):
        """Test getting organization by ID."""
        response = admin_client.get(f"/api/v2/admin/organizations/{test_organization.id}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == test_organization.id
        assert data["name"] == test_organization.name
        assert "user_count" in data
        assert "api_key_count" in data

    def test_get_organization_not_found(self, admin_client):
        """Test getting non-existent organization."""
        response = admin_client.get("/api/v2/admin/organizations/nonexistent_org")
        assert response.status_code == 404

    def test_create_organization(self, admin_client, db_session):
        """Test creating new organization."""
        from app.services.platform_settings_service import PlatformSettingsService as PSS

        response = admin_client.post(
            "/api/v2/admin/organizations",
            json={"name": "New Test Organization"},
        )
        assert response.status_code == 201
        data = response.json()

        # Project rule: IDs must always be prefixed
        assert data["id"].startswith("org_")
        assert data["name"] == "New Test Organization"
        # DB round-trip: row must actually exist with the returned id
        created = db_session.query(Organization).filter(Organization.id == data["id"]).first()
        assert created is not None
        assert created.name == "New Test Organization"

        # D-23: nothing reads these columns any more, but they are still written
        # with the effective instance values — a rollback restores images, not
        # schema, and an older image reads them.
        limits = PSS.get_instance_limits(db_session)
        assert created.rate_limit_per_minute == limits["rate_limit_per_minute"]
        assert created.rate_limit_per_day == limits["rate_limit_per_day"]

    def test_update_organization(self, admin_client, db_session, test_organization):
        """Test updating organization."""
        response = admin_client.patch(
            f"/api/v2/admin/organizations/{test_organization.id}",
            json={"name": "Updated Org Name"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Updated Org Name"
        # DB round-trip: relying on response body alone is not enough
        db_session.refresh(test_organization)
        assert test_organization.name == "Updated Org Name"

    def test_update_organization_not_found(self, admin_client):
        """Test updating non-existent organization."""
        response = admin_client.patch(
            "/api/v2/admin/organizations/nonexistent_org", json={"name": "New Name"}
        )
        assert response.status_code == 404

    def test_delete_organization(self, admin_client, db_session):
        """Test deleting organization (soft delete contract)."""
        # Create org to delete
        org = Organization(
            id="org_to_delete",
            name="Delete Me",
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()

        response = admin_client.delete("/api/v2/admin/organizations/org_to_delete")
        # Endpoint contract: 204 No Content
        assert response.status_code == 204

        # Endpoint contract: soft delete (row remains, is_active=False)
        deleted_org = (
            db_session.query(Organization).filter(Organization.id == "org_to_delete").first()
        )
        assert deleted_org is not None
        assert deleted_org.is_active is False

    def test_admin_delete_org_cascade_preserves_child_rows(self, admin_client, db_session):
        """DELETE /api/v2/admin/organizations/{id} is a soft delete and preserves child rows.

        Documents the current cascade contract: org delete is a SOFT delete
        (is_active=False). Child rows — users, API keys, models, executions —
        are NOT cascaded/cancelled. They remain in the DB attached to the
        now-inactive org.

        If the cascade contract changes (e.g., to hard delete with CASCADE
        FKs, or to disable cron schedules / cancel running solves), this
        test must be updated to assert the new behavior. Until then it
        guards against accidental cascade-removal regressions that would
        wipe out customer data.
        """
        from app.models import (
            APIKey,
            ModelExecution,
            ModelProject,
            User,
        )
        from app.shared.utils.datetime_helpers import utcnow
        from app.shared.utils.id_generator import generate_id

        org = Organization(
            id="org_cascade_target",
            name="Cascade Target Org",
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()

        # Seed: 1 user, 1 api key, 1 model project, 1 execution
        user = User(
            id=generate_id("usr_"),
            email="cascade@example.com",
            name="Cascade User",
            organization_id=org.id,
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        api_key = APIKey(
            id=generate_id("apk_"),
            user_id=user.id,
            organization_id=org.id,
            key_hash="cascade_hash_marker",
            key_prefix="ok_test_",
            name="Cascade Key",
            is_active=True,
            created_at=utcnow(),
        )
        db_session.add(api_key)

        project = ModelProject(
            id=generate_id("mp_"),
            organization_id=org.id,
            name="Cascade Model",
            status="active",
        )
        db_session.add(project)
        db_session.flush()

        execution = ModelExecution(
            id=generate_id("exe_"),
            organization_id=org.id,
            model_project_id=project.id,
            input_data={},
            status="completed",
        )
        db_session.add(execution)

        db_session.commit()

        # Capture seeded ids for post-delete assertions
        seeded_ids = {
            "user": user.id,
            "key": api_key.id,
            "model": project.id,
            "execution": execution.id,
        }

        # Perform admin delete
        response = admin_client.delete(f"/api/v2/admin/organizations/{org.id}")
        assert response.status_code == 204

        # Org row remains, marked inactive (soft delete)
        deleted_org = db_session.query(Organization).filter(Organization.id == org.id).first()
        assert deleted_org is not None
        assert deleted_org.is_active is False

        # ALL child rows must still exist (no cascade wipe)
        assert db_session.query(User).filter(User.id == seeded_ids["user"]).first() is not None, (
            "User row was wiped — soft delete contract violated"
        )
        assert (
            db_session.query(APIKey).filter(APIKey.id == seeded_ids["key"]).first() is not None
        ), "APIKey row was wiped — soft delete contract violated"
        assert (
            db_session.query(ModelProject).filter(ModelProject.id == seeded_ids["model"]).first()
            is not None
        ), "ModelProject row was wiped — soft delete contract violated"
        assert (
            db_session.query(ModelExecution)
            .filter(ModelExecution.id == seeded_ids["execution"])
            .first()
            is not None
        ), "ModelExecution row was wiped — soft delete contract violated"


class TestAdminOrganizationOverview:
    """Tests for the read-only organization overview endpoint."""

    def test_overview_happy_path(
        self, admin_client, db_session, test_organization, test_user, test_api_key
    ):
        """Overview aggregates the org's members, keys, models and stats."""
        from app.models import ModelExecution, ModelProject
        from app.shared.utils.id_generator import generate_id

        project = ModelProject(
            id=generate_id("mp_"),
            organization_id=test_organization.id,
            name="Overview Model",
            status="active",
        )
        db_session.add(project)
        db_session.flush()

        execution = ModelExecution(
            id=generate_id("exe_"),
            organization_id=test_organization.id,
            model_project_id=project.id,
            input_data={},
            status="completed",
        )
        db_session.add(execution)
        db_session.commit()

        response = admin_client.get(f"/api/v2/admin/organizations/{test_organization.id}/overview")
        assert response.status_code == 200
        data = response.json()

        # Org block
        assert data["organization"]["id"] == test_organization.id
        assert data["organization"]["name"] == test_organization.name
        assert "byok_configured" in data["organization"]

        # Members + keys
        assert test_user.id in [u["id"] for u in data["users"]]
        assert test_api_key.id in [k["id"] for k in data["api_keys"]]
        assert data["counts"]["users"] >= 1
        assert data["counts"]["api_keys"] >= 1

        # Models + executions surfaced (per-project rollups computed from executions)
        models_by_id = {m["id"]: m for m in data["models"]}
        assert project.id in models_by_id
        assert models_by_id[project.id]["display_name"] == "Overview Model"
        assert models_by_id[project.id]["total_executions"] == 1
        recent = {e["id"]: e for e in data["recent_executions"]}
        assert execution.id in recent
        assert recent[execution.id]["model_display_name"] == "Overview Model"
        assert data["counts"]["executions"] >= 1
        assert data["execution_stats"]["completed"] >= 1

        # Read-only view must never leak the API key secret material
        for key in data["api_keys"]:
            assert "key_hash" not in key
            assert key.get("full_key") is None

    def test_overview_scoped_to_org(
        self, admin_client, db_session, test_organization, test_user, test_user_2
    ):
        """Overview must only include rows belonging to the target org."""
        response = admin_client.get(f"/api/v2/admin/organizations/{test_organization.id}/overview")
        assert response.status_code == 200
        data = response.json()

        user_ids = [u["id"] for u in data["users"]]
        assert test_user.id in user_ids
        # A user from another org must NOT leak into this org's overview
        assert test_user_2.id not in user_ids
        for user in data["users"]:
            assert user["organization_id"] == test_organization.id

    def test_overview_not_found(self, admin_client):
        """Overview of a non-existent org returns 404."""
        response = admin_client.get("/api/v2/admin/organizations/nonexistent_org/overview")
        assert response.status_code == 404

    def test_overview_requires_admin(self, authenticated_client, test_organization):
        """Non-admin users cannot view an org overview."""
        response = authenticated_client.get(
            f"/api/v2/admin/organizations/{test_organization.id}/overview"
        )
        assert response.status_code == 403

    def test_overview_execution_stats_buckets(self, admin_client, db_session):
        """execution_stats folds statuses into completed / failed / running buckets.

        timeout + cancelled count as failed; pending counts as running. Uses a
        fresh org so the buckets are deterministic regardless of other rows.
        """
        from app.models import ModelExecution
        from app.shared.utils.id_generator import generate_id

        org = Organization(id=generate_id("org_"), name="Stats Org", is_active=True)
        db_session.add(org)
        db_session.flush()

        # one execution per terminal/active status
        for status, _ in [
            ("completed", 1),
            ("failed", 2),
            ("timeout", 3),
            ("cancelled", 4),
            ("running", 5),
            ("pending", 6),
        ]:
            db_session.add(
                ModelExecution(
                    id=generate_id("exe_"),
                    organization_id=org.id,
                    input_data={},
                    status=status,
                )
            )
        db_session.commit()

        response = admin_client.get(f"/api/v2/admin/organizations/{org.id}/overview")
        assert response.status_code == 200
        stats = response.json()["execution_stats"]

        assert stats["total"] == 6
        assert stats["completed"] == 1
        assert stats["failed"] == 3  # failed + timeout + cancelled
        assert stats["running"] == 2  # running + pending


class TestAdminUsers:
    """Tests for admin user endpoints."""

    def test_list_users(self, admin_client, db_session, test_user):
        """Test listing users."""
        response = admin_client.get("/api/v2/admin/users")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert data["total"] >= 1
        # Seeded user must appear
        assert test_user.id in [u["id"] for u in data["items"]]

    # CONTRACT-TEST: authenticated API responses must be uncacheable so a stale
    # empty list never gets served from browser/CDN cache (the "empty users"
    # bug). Do not delete in consolidation passes.
    def test_admin_list_is_not_cacheable(self, admin_client, db_session, test_user):
        """Admin list responses must carry Cache-Control: no-store."""
        response = admin_client.get("/api/v2/admin/users")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-store"

    def test_list_users_filter_by_org(
        self, admin_client, db_session, test_user, test_user_2, test_organization
    ):
        """Test filtering users by organization excludes other-org users."""
        response = admin_client.get(f"/api/v2/admin/users?organization_id={test_organization.id}")
        assert response.status_code == 200
        data = response.json()

        # Filter must actually exclude users from other orgs
        item_ids = [u["id"] for u in data["items"]]
        assert test_user.id in item_ids
        assert test_user_2.id not in item_ids
        for item in data["items"]:
            assert item["organization_id"] == test_organization.id

    def test_get_user(self, admin_client, db_session, test_user):
        """Test getting user by ID."""
        response = admin_client.get(f"/api/v2/admin/users/{test_user.id}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == test_user.id
        assert data["email"] == test_user.email

    def test_get_user_not_found(self, admin_client):
        """Test getting non-existent user."""
        response = admin_client.get("/api/v2/admin/users/nonexistent_user")
        assert response.status_code == 404

    def test_create_user(self, admin_client, db_session, test_organization):
        """Test creating new user."""
        response = admin_client.post(
            "/api/v2/admin/users",
            json={
                "organization_id": test_organization.id,
                "name": "New Test User",
                "email": "newuser@example.com",
            },
        )
        assert response.status_code == 201
        data = response.json()

        # Project rule: IDs must always be prefixed
        assert data["id"].startswith("usr_")
        assert data["name"] == "New Test User"
        assert data["email"] == "newuser@example.com"
        # DB round-trip
        created = db_session.query(User).filter(User.id == data["id"]).first()
        assert created is not None
        assert created.email == "newuser@example.com"
        assert created.organization_id == test_organization.id

    def test_update_user(self, admin_client, db_session, test_user):
        """Test updating user."""
        response = admin_client.patch(
            f"/api/v2/admin/users/{test_user.id}", json={"name": "Updated User Name"}
        )
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Updated User Name"
        # DB round-trip
        db_session.refresh(test_user)
        assert test_user.name == "Updated User Name"

    def test_update_user_not_found(self, admin_client):
        """Test updating non-existent user."""
        response = admin_client.patch(
            "/api/v2/admin/users/nonexistent_user", json={"name": "New Name"}
        )
        assert response.status_code == 404

    def test_delete_user(self, admin_client, db_session, test_organization):
        """Test deleting user (soft delete contract)."""
        # Create user to delete
        user = User(
            id="user_to_delete",
            name="Delete Me",
            email="deleteme@example.com",
            organization_id=test_organization.id,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        response = admin_client.delete("/api/v2/admin/users/user_to_delete")
        # Endpoint contract: 204 No Content
        assert response.status_code == 204

        # Endpoint contract: soft delete
        deleted = db_session.query(User).filter(User.id == "user_to_delete").first()
        assert deleted is not None
        assert deleted.is_active is False


class TestAdminUserEditsAreChecked:
    """What the admin panel is allowed to write into an account.

    Found by driving the panel (QA sweep, 2026-08-20): the email field took
    anything, an address another account already had gave a 500, and an
    administrator could clear its own Admin tick and be locked out one request
    later.
    """

    def test_an_email_that_is_not_one_is_refused(self, admin_client, db_session, test_user):
        before = test_user.email
        response = admin_client.patch(
            f"/api/v2/admin/users/{test_user.id}", json={"email": "not an email"}
        )
        assert response.status_code == 422, response.text
        db_session.refresh(test_user)
        assert test_user.email == before

    def test_an_address_in_capitals_is_stored_lowercased(self, admin_client, db_session, test_user):
        # The login lookup is lowercased since the email-case fix, so an address
        # stored with capitals is an account nobody can sign in to.
        response = admin_client.patch(
            f"/api/v2/admin/users/{test_user.id}", json={"email": "MiXeD.Case@Example.COM"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["email"] == "mixed.case@example.com"
        db_session.refresh(test_user)
        assert test_user.email == "mixed.case@example.com"

    def test_an_address_another_account_has_answers_409_not_500(
        self, admin_client, db_session, test_organization, test_user, test_admin_user
    ):
        response = admin_client.patch(
            f"/api/v2/admin/users/{test_user.id}", json={"email": test_admin_user.email}
        )
        assert response.status_code == 409, response.text
        # CONTRACT-TEST: this is the ordinary "that address is taken" answer. It
        # used to reach the person as a 500 saying "internal error".
        assert response.json()["code"] == "admin.email_taken"

    def test_creating_a_second_account_on_a_taken_address_answers_409(
        self, admin_client, test_organization, test_user
    ):
        response = admin_client.post(
            "/api/v2/admin/users",
            json={
                "organization_id": test_organization.id,
                "name": "Duplicate",
                "email": test_user.email,
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "admin.email_taken"

    def test_an_admin_cannot_clear_its_own_admin_tick(
        self, admin_client, db_session, test_admin_user
    ):
        response = admin_client.patch(
            f"/api/v2/admin/users/{test_admin_user.id}", json={"is_admin": False}
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "admin.cannot_demote_self"
        db_session.refresh(test_admin_user)
        assert test_admin_user.role == "admin"

    def test_an_admin_cannot_deactivate_itself(self, admin_client, db_session, test_admin_user):
        response = admin_client.patch(
            f"/api/v2/admin/users/{test_admin_user.id}", json={"is_active": False}
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "admin.cannot_deactivate_self"
        db_session.refresh(test_admin_user)
        assert test_admin_user.is_active is True

    def test_an_admin_cannot_delete_its_own_account(
        self, admin_client, db_session, test_admin_user
    ):
        response = admin_client.delete(f"/api/v2/admin/users/{test_admin_user.id}")
        assert response.status_code == 409, response.text
        db_session.refresh(test_admin_user)
        assert test_admin_user.is_active is True

    def test_an_admin_may_still_demote_somebody_else(
        self, admin_client, db_session, test_organization
    ):
        other = User(
            id="usr_other_admin",
            name="Other Admin",
            email="other-admin@example.com",
            organization_id=test_organization.id,
            role="admin",
            is_active=True,
        )
        db_session.add(other)
        db_session.commit()

        response = admin_client.patch(
            "/api/v2/admin/users/usr_other_admin", json={"is_admin": False}
        )
        assert response.status_code == 200, response.text
        db_session.refresh(other)
        assert other.role == "member"


class TestAdminAPIKeys:
    """Tests for admin API key endpoints."""

    def test_list_api_keys(self, admin_client, db_session, test_api_key):
        """Test listing API keys."""
        response = admin_client.get("/api/v2/admin/api-keys")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert data["total"] >= 1
        assert test_api_key.id in [k["id"] for k in data["items"]]

    def test_list_api_keys_filter_by_org(
        self, admin_client, db_session, test_api_key, test_organization, test_user_2
    ):
        """Test filtering API keys by organization excludes other-org keys."""
        from app.services.auth.api_key_service import APIKeyService

        # Create a second-org key so the filter actually has data to exclude
        other_key, _ = APIKeyService.create_api_key(
            db=db_session,
            user_id=test_user_2.id,
            organization_id=test_user_2.organization_id,
            name="Other Org Key",
            prefix="ok_test_",
        )
        db_session.commit()

        response = admin_client.get(
            f"/api/v2/admin/api-keys?organization_id={test_organization.id}"
        )
        assert response.status_code == 200
        data = response.json()

        item_ids = [k["id"] for k in data["items"]]
        assert test_api_key.id in item_ids
        assert other_key.id not in item_ids
        for item in data["items"]:
            assert item["organization_id"] == test_organization.id

    def test_toggle_api_key(self, admin_client, db_session, test_api_key):
        """Test toggling API key active status."""
        original_status = test_api_key.is_active

        response = admin_client.patch(f"/api/v2/admin/api-keys/{test_api_key.id}/toggle")
        assert response.status_code == 200

        db_session.refresh(test_api_key)
        assert test_api_key.is_active != original_status

    def test_delete_api_key(self, admin_client, db_session, test_organization, test_user):
        """Test deleting API key (hard delete contract)."""
        from app.services.auth.api_key_service import APIKeyService

        # Create key to delete
        api_key, _ = APIKeyService.create_api_key(
            db=db_session,
            user_id=test_user.id,
            organization_id=test_organization.id,
            name="Key to Delete",
            prefix="ok_test_",
        )
        key_id = api_key.id
        db_session.commit()

        response = admin_client.delete(f"/api/v2/admin/api-keys/{key_id}")
        # Endpoint contract: 204 No Content
        assert response.status_code == 204

        # Endpoint contract: hard delete (row is gone, not just deactivated)
        deleted = db_session.query(APIKey).filter(APIKey.id == key_id).first()
        assert deleted is None


class TestAdminModels:
    """Tests for admin models endpoints (marketplace listings, P1.5 fusion)."""

    def _make_listing(self, db_session, test_organization, pid: str) -> ModelProjectListing:
        from app.models import ModelProject

        db_session.add(
            ModelProject(
                id=pid,
                organization_id=test_organization.id,
                name="Admin " + pid,
                status="active",
            )
        )
        db_session.flush()
        listing = ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Admin Listing " + pid,
            description="For admin testing",
            category=ModelCategory.GENERAL.value,
            version="1.0.0",
            status="published",
            is_official=False,
            is_featured=False,
            is_public=True,
            author_organization_id=test_organization.id,
        )
        db_session.add(listing)
        db_session.commit()
        return listing

    def test_list_catalog_models(self, admin_client, db_session, test_organization):
        """Test listing marketplace listings."""
        self._make_listing(db_session, test_organization, "admin_test_model")

        response = admin_client.get("/api/v2/admin/models")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert data["total"] >= 1
        assert "admin_test_model" in [m["id"] for m in data["items"]]

    def test_list_models_search_matches_the_term(self, admin_client, db_session, test_organization):
        """A search term narrows the list to the listings that carry it."""
        self._make_listing(db_session, test_organization, "admin_search_hit")
        self._make_listing(db_session, test_organization, "admin_search_other")

        response = admin_client.get("/api/v2/admin/models?search=search_hit")
        assert response.status_code == 200
        data = response.json()

        ids = [m["id"] for m in data["items"]]
        assert "admin_search_hit" in ids
        assert "admin_search_other" not in ids

    # CONTRACT-TEST: a search that matches nothing returns nothing, never the
    # unfiltered list. The endpoint accepted `search` and dropped it, so an
    # admin reading the answer saw every listing and called them all matches.
    def test_list_models_search_with_no_match_returns_nothing(
        self, admin_client, db_session, test_organization
    ):
        """A term that matches no listing returns an empty page, not every row."""
        self._make_listing(db_session, test_organization, "admin_search_present")

        response = admin_client.get("/api/v2/admin/models?search=zzz_no_such_listing_zzz")
        assert response.status_code == 200
        data = response.json()

        assert data["items"] == []
        assert data["total"] == 0

    def test_list_models_search_matches_display_name(
        self, admin_client, db_session, test_organization
    ):
        """The display name an admin reads on screen is searchable too."""
        self._make_listing(db_session, test_organization, "admin_display_search")

        response = admin_client.get("/api/v2/admin/models?search=Admin Listing admin_display")
        assert response.status_code == 200

        ids = [m["id"] for m in response.json()["items"]]
        assert "admin_display_search" in ids

    def test_update_model_badges(self, admin_client, db_session, test_organization):
        """Test updating listing badges (official, featured)."""
        listing = self._make_listing(db_session, test_organization, "admin_badge_model")

        response = admin_client.patch(
            "/api/v2/admin/models/admin_badge_model",
            json={"is_official": True, "is_featured": True},
        )
        assert response.status_code == 200

        db_session.refresh(listing)
        assert listing.is_official
        assert listing.is_featured

    def test_toggle_visibility(self, admin_client, db_session, test_organization):
        """Test toggling listing visibility."""
        listing = self._make_listing(db_session, test_organization, "admin_vis_model")

        response = admin_client.patch(
            "/api/v2/admin/models/admin_vis_model/visibility?is_public=false"
        )
        assert response.status_code == 200

        db_session.refresh(listing)
        assert listing.is_public is False


class TestAdminRequiresAuth:
    """Tests verifying admin endpoints require admin authentication."""

    def test_list_organizations_requires_admin(self, authenticated_client):
        """Test that non-admin cannot access admin endpoints."""
        response = authenticated_client.get("/api/v2/admin/organizations")
        assert response.status_code == 403

    def test_list_users_requires_admin(self, authenticated_client):
        """Test that non-admin cannot list users."""
        response = authenticated_client.get("/api/v2/admin/users")
        assert response.status_code == 403

    def test_create_organization_requires_admin(self, authenticated_client):
        """Test that non-admin cannot create organizations."""
        response = authenticated_client.post(
            "/api/v2/admin/organizations", json={"name": "Hacked Org"}
        )
        assert response.status_code == 403
