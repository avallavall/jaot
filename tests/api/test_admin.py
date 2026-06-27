"""
Tests for Admin API endpoints.

These tests verify the admin CRUD functionality:
- Organizations CRUD
- Users CRUD
- API Keys management
- Credits/Transactions
- Models management
"""

from app.models import (
    APIKey,
    CreditTransaction,
    ModelCatalog,
    ModelCategory,
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

    def test_list_organizations_filter_by_plan(self, admin_client, db_session):
        """Test filtering organizations by plan."""
        # Create org with specific plan
        org = Organization(
            id="org_plan_test",
            name="Plan Test Org",
            plan="business",
            credits_balance=1000,
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()

        response = admin_client.get("/api/v2/admin/organizations?plan=business")
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["plan"] == "business"

    def test_list_organizations_pagination(self, admin_client, db_session, test_organization):
        """Test organization pagination."""
        # Create multiple orgs (5 here + at least the test org → page 1 must be full)
        for i in range(5):
            org = Organization(
                id=f"org_pagination_{i}",
                name=f"Pagination Org {i}",
                credits_balance=100,
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
        response = admin_client.post(
            "/api/v2/admin/organizations",
            json={
                "name": "New Test Organization",
                "plan": "pro",
                "credits_balance": 500,
                "monthly_quota": 500,
            },
        )
        assert response.status_code == 201
        data = response.json()

        # Project rule: IDs must always be prefixed
        assert data["id"].startswith("org_")
        assert data["name"] == "New Test Organization"
        assert data["plan"] == "pro"
        assert data["credits_balance"] == 500
        # DB round-trip: row must actually exist with the returned id
        created = db_session.query(Organization).filter(Organization.id == data["id"]).first()
        assert created is not None
        assert created.name == "New Test Organization"
        assert created.plan == "pro"
        assert created.credits_balance == 500

    def test_update_organization(self, admin_client, db_session, test_organization):
        """Test updating organization."""
        response = admin_client.patch(
            f"/api/v2/admin/organizations/{test_organization.id}",
            json={"name": "Updated Org Name", "credits_balance": 2000},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Updated Org Name"
        assert data["credits_balance"] == 2000
        # DB round-trip: relying on response body alone is not enough
        db_session.refresh(test_organization)
        assert test_organization.name == "Updated Org Name"
        assert test_organization.credits_balance == 2000

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
            credits_balance=100,
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
        (is_active=False). Child rows — users, API keys, models, executions,
        credit transactions — are NOT cascaded/cancelled. They remain in the
        DB attached to the now-inactive org.

        If the cascade contract changes (e.g., to hard delete with CASCADE
        FKs, or to disable cron schedules / cancel running solves), this
        test must be updated to assert the new behavior. Until then it
        guards against accidental cascade-removal regressions that would
        wipe out customer data.
        """
        from app.models import (
            APIKey,
            CreditTransaction,
            ModelExecution,
            OrganizationModel,
            User,
        )
        from app.shared.utils.datetime_helpers import utcnow
        from app.shared.utils.id_generator import generate_id

        org = Organization(
            id="org_cascade_target",
            name="Cascade Target Org",
            credits_balance=500,
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()

        # Seed: 1 user, 1 api key, 1 org-model, 1 execution, 1 credit transaction
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

        org_model = OrganizationModel(
            id=generate_id("om_"),
            organization_id=org.id,
            custom_name="Cascade Model",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.flush()

        execution = ModelExecution(
            id=generate_id("exe_"),
            organization_id=org.id,
            organization_model_id=org_model.id,
            input_data={},
            status="completed",
            credits_consumed=1,
        )
        db_session.add(execution)

        tx = CreditTransaction(
            id=generate_id("ctx_"),
            organization_id=org.id,
            credits_amount=100,
            balance_after=600,
            transaction_type="purchase",
            description="Cascade test transaction",
        )
        db_session.add(tx)
        db_session.commit()

        # Capture seeded ids for post-delete assertions
        seeded_ids = {
            "user": user.id,
            "key": api_key.id,
            "model": org_model.id,
            "execution": execution.id,
            "tx": tx.id,
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
            db_session.query(OrganizationModel)
            .filter(OrganizationModel.id == seeded_ids["model"])
            .first()
            is not None
        ), "OrganizationModel row was wiped — soft delete contract violated"
        assert (
            db_session.query(ModelExecution)
            .filter(ModelExecution.id == seeded_ids["execution"])
            .first()
            is not None
        ), "ModelExecution row was wiped — soft delete contract violated"
        assert (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.id == seeded_ids["tx"])
            .first()
            is not None
        ), "CreditTransaction row was wiped — soft delete contract violated"


class TestAdminOrganizationOverview:
    """Tests for the read-only organization overview endpoint."""

    def test_overview_happy_path(
        self, admin_client, db_session, test_organization, test_user, test_api_key
    ):
        """Overview aggregates the org's members, keys, models and stats."""
        from app.models import CreditTransaction, ModelExecution, OrganizationModel
        from app.shared.utils.id_generator import generate_id

        org_model = OrganizationModel(
            id=generate_id("om_"),
            organization_id=test_organization.id,
            custom_name="Overview Model",
            is_active=True,
            total_executions=2,
            total_credits_used=4,
        )
        db_session.add(org_model)
        db_session.flush()

        execution = ModelExecution(
            id=generate_id("exe_"),
            organization_id=test_organization.id,
            organization_model_id=org_model.id,
            input_data={},
            status="completed",
            credits_consumed=3,
        )
        tx = CreditTransaction(
            id=generate_id("ctx_"),
            organization_id=test_organization.id,
            credits_amount=100,
            balance_after=100,
            transaction_type="purchase",
            description="Overview test transaction",
        )
        db_session.add_all([execution, tx])
        db_session.commit()

        response = admin_client.get(f"/api/v2/admin/organizations/{test_organization.id}/overview")
        assert response.status_code == 200
        data = response.json()

        # Org block
        assert data["organization"]["id"] == test_organization.id
        assert data["organization"]["plan"] == test_organization.plan
        assert "byok_configured" in data["organization"]

        # Members + keys
        assert test_user.id in [u["id"] for u in data["users"]]
        assert test_api_key.id in [k["id"] for k in data["api_keys"]]
        assert data["counts"]["users"] >= 1
        assert data["counts"]["api_keys"] >= 1

        # Models + executions + transactions surfaced
        assert org_model.id in [m["id"] for m in data["models"]]
        assert execution.id in [e["id"] for e in data["recent_executions"]]
        assert tx.id in [t["id"] for t in data["recent_transactions"]]
        assert data["counts"]["executions"] >= 1
        assert data["execution_stats"]["completed"] >= 1
        assert data["execution_stats"]["credits_consumed_total"] >= 3

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


class TestAdminCredits:
    """Tests for admin credits endpoints."""

    def test_list_transactions(self, admin_client, db_session, test_organization):
        """Test listing credit transactions."""
        tx = CreditTransaction(
            id="tx_test_list",
            organization_id=test_organization.id,
            credits_amount=100,
            balance_after=100,
            transaction_type="purchase",
            description="Test transaction",
        )
        db_session.add(tx)
        db_session.commit()

        response = admin_client.get("/api/v2/admin/credits/transactions")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert data["total"] >= 1

    def test_list_transactions_filter_by_org(
        self, admin_client, db_session, test_organization, test_organization_2
    ):
        """Test filtering transactions by organization excludes other-org rows."""
        own_tx = CreditTransaction(
            id="tx_filter_own",
            organization_id=test_organization.id,
            credits_amount=100,
            balance_after=100,
            transaction_type="purchase",
            description="Own transaction",
        )
        other_tx = CreditTransaction(
            id="tx_filter_other",
            organization_id=test_organization_2.id,
            credits_amount=50,
            balance_after=50,
            transaction_type="purchase",
            description="Other-org transaction",
        )
        db_session.add_all([own_tx, other_tx])
        db_session.commit()

        response = admin_client.get(
            f"/api/v2/admin/credits/transactions?organization_id={test_organization.id}"
        )
        assert response.status_code == 200
        data = response.json()

        item_ids = [t["id"] for t in data["items"]]
        assert "tx_filter_own" in item_ids
        assert "tx_filter_other" not in item_ids
        for item in data["items"]:
            assert item["organization_id"] == test_organization.id

    def test_add_credits(self, admin_client, db_session, test_organization):
        """Test adding credits to organization."""
        initial_balance = test_organization.credits_balance

        response = admin_client.post(
            "/api/v2/admin/credits/adjust",
            json={
                "organization_id": test_organization.id,
                "amount": 500,
                "reason": "Admin credit grant",
            },
        )
        assert response.status_code == 200

        db_session.refresh(test_organization)
        assert test_organization.credits_balance == initial_balance + 500


class TestAdminModels:
    """Tests for admin models endpoints."""

    def test_list_catalog_models(self, admin_client, db_session):
        """Test listing catalog models."""
        model = ModelCatalog(
            id="admin_test_model",
            name="admin_test",
            display_name="Admin Test Model",
            description="For admin testing",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(model)
        db_session.commit()

        response = admin_client.get("/api/v2/admin/models")
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert data["total"] >= 1

    def test_update_model_badges(self, admin_client, db_session):
        """Test updating model badges (official, featured)."""
        model = ModelCatalog(
            id="admin_badge_model",
            name="badge_test",
            display_name="Badge Test Model",
            description="For badge testing",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_featured=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(model)
        db_session.commit()

        response = admin_client.patch(
            f"/api/v2/admin/models/{model.id}", json={"is_official": True, "is_featured": True}
        )
        assert response.status_code == 200

        db_session.refresh(model)
        assert model.is_official
        assert model.is_featured


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
