"""Tests for admin settings API — registry, service, and CRUD endpoints.

Covers requirements: ADMIN-01, ADMIN-02, ADMIN-03, ADMIN-04.
"""

from app.models.platform_setting import PlatformSetting


class TestSettingsRegistry:
    """Test the settings registry data structure."""

    def test_registry_has_all_categories(self):
        """ADMIN-01: Registry covers all 8 categories."""
        from app.services.settings_registry import REGISTRY_BY_CATEGORY, SettingCategory

        expected = {
            SettingCategory.BILLING,
            SettingCategory.SOLVER,
            SettingCategory.LLM,
            SettingCategory.EMAIL,
            SettingCategory.SECURITY,
            SettingCategory.MARKETPLACE,
            SettingCategory.SECRETS,
        }
        actual = set(REGISTRY_BY_CATEGORY.keys())
        assert expected.issubset(actual), f"Missing categories: {expected - actual}"

    def test_registry_has_minimum_entries(self):
        """Registry contains 88+ entries across all categories."""
        from app.services.settings_registry import SETTINGS_REGISTRY

        assert len(SETTINGS_REGISTRY) >= 88, f"Expected >= 88 entries, got {len(SETTINGS_REGISTRY)}"

    def test_registry_by_key_lookup(self):
        """REGISTRY_BY_KEY allows key-based lookup."""
        from app.services.settings_registry import REGISTRY_BY_KEY

        # Solver setting
        assert "SOLVER_DEFAULT_TIMEOUT" in REGISTRY_BY_KEY
        defn = REGISTRY_BY_KEY["SOLVER_DEFAULT_TIMEOUT"]
        assert defn.setting_type.value == "int"
        assert defn.min_value == 1
        assert defn.max_value == 3600

    def test_registry_by_category_groups_correctly(self):
        """REGISTRY_BY_CATEGORY groups settings by their category."""
        from app.services.settings_registry import (
            REGISTRY_BY_CATEGORY,
            SettingCategory,
        )

        solver_settings = REGISTRY_BY_CATEGORY[SettingCategory.SOLVER]
        solver_keys = {s.key for s in solver_settings}
        assert "SOLVER_DEFAULT_TIMEOUT" in solver_keys
        assert "SOLVER_POOL_SIZE" in solver_keys

    def test_secret_settings_are_editable(self):
        """Secret settings must have is_secret=True and is_readonly=False (editable)."""
        from app.services.settings_registry import (
            REGISTRY_BY_CATEGORY,
            SettingCategory,
        )

        secrets = REGISTRY_BY_CATEGORY[SettingCategory.SECRETS]
        for s in secrets:
            assert s.is_secret is True, f"{s.key} should be is_secret=True"
            assert s.is_readonly is False, f"{s.key} should be is_readonly=False"

    def test_plan_tier_keys_exist(self):
        """Billing category has all plan tier keys (4 tiers x 9 fields)."""
        from app.services.settings_registry import REGISTRY_BY_KEY

        tiers = ["free", "starter", "pro", "business"]
        fields = [
            "credits",
            "monthly_quota",
            "rate_limit_per_minute",
            "rate_limit_per_day",
            "max_solve_time_seconds",
            "max_variables",
            "max_daily_solves",
            "max_cron_schedules",
            "allowed_features",
        ]
        for tier in tiers:
            for field in fields:
                key = f"plan_{tier}_{field}"
                assert key in REGISTRY_BY_KEY, f"Missing plan key: {key}"


class TestPlatformSettingsServiceGet:
    """ADMIN-04: DB-then-env fallback chain."""

    def test_get_returns_db_value_when_set(self, db_session):
        """get() returns DB value when a row exists."""
        from app.services.platform_settings_service import PlatformSettingsService

        # Set a value in DB
        PlatformSettingsService.set(db_session, "SOLVER_DEFAULT_TIMEOUT", "999")
        db_session.flush()

        value = PlatformSettingsService.get(db_session, "SOLVER_DEFAULT_TIMEOUT")
        assert value == "999"

    def test_get_returns_seeded_value(self, db_session):
        """get() returns the seeded DB value for a registered key."""
        from app.services.platform_settings_service import PlatformSettingsService

        # SOLVER_DEFAULT_TIMEOUT is seeded from registry defaults
        value = PlatformSettingsService.get(db_session, "SOLVER_DEFAULT_TIMEOUT")
        assert value != ""
        int(value)  # Should be parseable as int

    def test_get_falls_back_to_registry_default(self, db_session):
        """get() falls back to registry default_value."""
        from app.services.platform_settings_service import PlatformSettingsService

        value = PlatformSettingsService.get(db_session, "marketplace_commission_rate")
        assert value == "0.10"


class TestPlatformSettingsServiceBulkSet:
    """ADMIN-02 + ADMIN-03: Bulk set with audit."""

    def test_bulk_set_creates_audit_records(self, db_session):
        """bulk_set() updates settings and creates audit records."""
        from app.services.platform_settings_service import PlatformSettingsService

        updates = {
            "SOLVER_DEFAULT_TIMEOUT": "120",
            "SOLVER_POOL_SIZE": "8",
        }
        audits = PlatformSettingsService.bulk_set(db_session, updates, changed_by="admin@test.com")
        db_session.flush()

        assert len(audits) >= 2
        keys = {a.setting_key for a in audits}
        assert "SOLVER_DEFAULT_TIMEOUT" in keys
        assert "SOLVER_POOL_SIZE" in keys

    def test_bulk_set_updates_secrets(self, db_session):
        """bulk_set() now processes secret settings (no longer readonly)."""
        from app.services.platform_settings_service import PlatformSettingsService

        updates = {
            "DATABASE_URL": "postgresql://new-db-url",
            "SOLVER_DEFAULT_TIMEOUT": "120",
        }
        audits = PlatformSettingsService.bulk_set(db_session, updates, changed_by="admin@test.com")
        db_session.flush()

        audit_keys = {a.setting_key for a in audits}
        # Both should be updated since secrets are no longer readonly
        assert "DATABASE_URL" in audit_keys
        assert "SOLVER_DEFAULT_TIMEOUT" in audit_keys

    def test_bulk_set_skips_unchanged(self, db_session):
        """bulk_set() skips settings whose value hasn't changed."""
        from app.services.platform_settings_service import PlatformSettingsService

        # Set value first
        PlatformSettingsService.set(db_session, "SOLVER_DEFAULT_TIMEOUT", "300")
        db_session.flush()

        # Try to set the same value
        audits = PlatformSettingsService.bulk_set(
            db_session, {"SOLVER_DEFAULT_TIMEOUT": "300"}, changed_by="admin@test.com"
        )
        assert len(audits) == 0


class TestPlatformSettingsServiceReset:
    """ADMIN-03 + ADMIN-04: Reset to default."""

    def test_reset_writes_registry_default(self, db_session):
        """reset_to_default() writes registry default back and creates audit."""
        from app.services.platform_settings_service import PlatformSettingsService
        from app.services.settings_registry import REGISTRY_BY_KEY

        # Set a non-default value
        PlatformSettingsService.set(
            db_session,
            "SOLVER_DEFAULT_TIMEOUT",
            "999",
        )
        db_session.flush()

        audit = PlatformSettingsService.reset_to_default(
            db_session,
            "SOLVER_DEFAULT_TIMEOUT",
            changed_by="admin@test.com",
        )
        db_session.flush()

        registry_default = REGISTRY_BY_KEY["SOLVER_DEFAULT_TIMEOUT"].default_value

        assert audit is not None
        assert audit.old_value == "999"
        assert audit.new_value == registry_default

        # DB row should still exist with the default value
        row = (
            db_session.query(PlatformSetting)
            .filter(PlatformSetting.key == "SOLVER_DEFAULT_TIMEOUT")
            .first()
        )
        assert row is not None
        assert row.value == registry_default


class TestPlatformSettingsServiceValidation:
    """ADMIN-02: Validation against registry constraints."""

    def test_validate_rejects_out_of_range(self):
        """validate_value() rejects out-of-range numbers."""
        from app.services.platform_settings_service import PlatformSettingsService

        ok, err = PlatformSettingsService.validate_value("SOLVER_DEFAULT_TIMEOUT", "9999")
        assert ok is False
        assert err is not None

    def test_validate_rejects_wrong_type(self):
        """validate_value() rejects wrong types."""
        from app.services.platform_settings_service import PlatformSettingsService

        ok, err = PlatformSettingsService.validate_value("SOLVER_DEFAULT_TIMEOUT", "not_a_number")
        assert ok is False
        assert err is not None

    def test_validate_accepts_valid(self):
        """validate_value() accepts valid values."""
        from app.services.platform_settings_service import PlatformSettingsService

        ok, err = PlatformSettingsService.validate_value("SOLVER_DEFAULT_TIMEOUT", "120")
        assert ok is True
        assert err is None


class TestSettingsRegistryEndpoint:
    """ADMIN-01: GET /admin/settings/registry."""

    def test_registry_returns_200(self, admin_client):
        """Returns full registry grouped by category."""
        response = admin_client.get("/api/v2/admin/settings/registry")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        # Should have solver, llm, etc.
        assert "solver" in data["categories"]
        assert "llm" in data["categories"]
        assert "secrets" in data["categories"]

    def test_registry_entries_have_metadata(self, admin_client):
        """Each entry has key, label, type, category."""
        response = admin_client.get("/api/v2/admin/settings/registry")
        data = response.json()
        solver_entries = data["categories"]["solver"]
        assert len(solver_entries) >= 4
        entry = solver_entries[0]
        assert "key" in entry
        assert "label" in entry
        assert "setting_type" in entry


class TestSettingsValuesEndpoint:
    """ADMIN-01: GET /admin/settings/values."""

    def test_values_returns_200(self, admin_client):
        """Returns all current setting values (T4: status + Pydantic + default-value invariant).

        TA-05 (HIGH auth): Strengthened from T3 shape-only ("key existence")
        to T4 — asserts the response roundtrips through SettingsValuesResponse
        AND the SOLVER_DEFAULT_TIMEOUT value matches the registry default
        declared in app/services/settings_registry.py. The previous shape
        ("settings" key present + key exists) tolerated a regression that
        served stale or hardcoded values for solver settings.
        """
        from app.schemas.admin_settings import SettingsValuesResponse
        from app.services.settings_registry import REGISTRY_BY_KEY

        response = admin_client.get("/api/v2/admin/settings/values")

        # Tier-1: status
        assert response.status_code == 200, response.text

        data = response.json()

        # Tier-4: Pydantic schema roundtrip (validates response shape end-to-end)
        parsed = SettingsValuesResponse.model_validate(data)
        assert "SOLVER_DEFAULT_TIMEOUT" in parsed.settings, (
            "SOLVER_DEFAULT_TIMEOUT missing from /admin/settings/values response"
        )

        # Tier-4: default-value invariant — the served value must equal the
        # registry default (the seeded value, before any admin override).
        registry_default = REGISTRY_BY_KEY["SOLVER_DEFAULT_TIMEOUT"].default_value
        served_value = parsed.settings["SOLVER_DEFAULT_TIMEOUT"].value
        assert served_value == registry_default, (
            f"SOLVER_DEFAULT_TIMEOUT served {served_value!r} does not match "
            f"registry default {registry_default!r}"
        )

    def test_values_non_admin_returns_403(self, authenticated_client):
        """TA-05 edge: non-admin user gets 403 on /admin/settings/values.

        The admin router gates all /admin/* routes with get_admin_user. A
        regular API-key authenticated user must NOT receive any settings
        data — admin-only secrets and platform configuration are at stake.
        """
        response = authenticated_client.get("/api/v2/admin/settings/values")
        assert response.status_code == 403, response.text

    def test_values_secrets_masked(self, admin_client):
        """Secret values are masked as ****."""
        response = admin_client.get("/api/v2/admin/settings/values")
        data = response.json()
        # DATABASE_URL should be masked
        if "DATABASE_URL" in data["settings"]:
            val = data["settings"]["DATABASE_URL"]["value"]
            assert val in ("****", ""), f"Secret not masked: {val}"

    def test_values_filter_by_category(self, admin_client):
        """Filtering by category returns only that category."""
        response = admin_client.get("/api/v2/admin/settings/values?category=solver")
        assert response.status_code == 200
        data = response.json()
        # All returned settings should be solver category
        from app.services.settings_registry import REGISTRY_BY_KEY, SettingCategory

        for key in data["settings"]:
            defn = REGISTRY_BY_KEY.get(key)
            assert defn is not None, f"Unknown key in response: {key}"
            assert defn.category == SettingCategory.SOLVER


class TestSettingsUpdateEndpoint:
    """ADMIN-02: PUT /admin/settings/values."""

    def test_update_valid_returns_200(self, admin_client, db_session):
        """Valid update returns 200 and persists."""
        response = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"SOLVER_DEFAULT_TIMEOUT": "120"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "SOLVER_DEFAULT_TIMEOUT" in data["updated"]

        # Verify persisted
        from app.services.platform_settings_service import PlatformSettingsService

        val = PlatformSettingsService.get(db_session, "SOLVER_DEFAULT_TIMEOUT")
        assert val == "120"

    def test_update_invalid_returns_errors(self, admin_client):
        """Out-of-range value returns 200 with errors dict."""
        response = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"SOLVER_DEFAULT_TIMEOUT": "99999"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "SOLVER_DEFAULT_TIMEOUT" in data["errors"]

    def test_update_secret_persists(self, admin_client, db_session):
        """Secret keys can now be updated via admin API."""
        response = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"JWT_SECRET": "new-super-secret-value"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "JWT_SECRET" in data["updated"]

        # Verify value is masked on read-back
        response = admin_client.get("/api/v2/admin/settings/values?category=secrets")
        data = response.json()
        assert data["settings"]["JWT_SECRET"]["value"] == "****"


class TestSettingsResetEndpoint:
    """ADMIN-03 + ADMIN-04: POST /admin/settings/reset/{key}."""

    def test_reset_reverts_to_default(self, admin_client, db_session):
        """Reset writes registry default back to DB row."""
        from app.services.settings_registry import REGISTRY_BY_KEY

        # First set a custom value
        admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"SOLVER_DEFAULT_TIMEOUT": "999"}},
        )

        # Reset
        response = admin_client.post("/api/v2/admin/settings/reset/SOLVER_DEFAULT_TIMEOUT")
        assert response.status_code == 200

        registry_default = REGISTRY_BY_KEY["SOLVER_DEFAULT_TIMEOUT"].default_value

        # DB row should still exist with registry default
        db_session.expire_all()
        row = (
            db_session.query(PlatformSetting)
            .filter(PlatformSetting.key == "SOLVER_DEFAULT_TIMEOUT")
            .first()
        )
        assert row is not None
        assert row.value == registry_default


class TestSettingsAuditEndpoint:
    """ADMIN-03: GET /admin/settings/audit."""

    def test_audit_returns_entries(self, admin_client):
        """Audit log returns entries after a change."""
        admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"SOLVER_DEFAULT_TIMEOUT": "777"}},
        )

        response = admin_client.get("/api/v2/admin/settings/audit")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert data["total"] >= 1
        assert data["items"][0]["setting_key"] == "SOLVER_DEFAULT_TIMEOUT"

    def test_audit_filter_by_category(self, admin_client):
        """Audit log can be filtered by category."""
        admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"SOLVER_DEFAULT_TIMEOUT": "888"}},
        )

        response = admin_client.get("/api/v2/admin/settings/audit?category=solver")
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["category"] == "solver"


class TestSettingsPlansEndpoint:
    """ADMIN-02: GET/PUT /admin/settings/plans."""

    def test_get_plans_returns_all_tiers(self, admin_client):
        """GET /plans returns all 4 plan tiers."""
        response = admin_client.get("/api/v2/admin/settings/plans")
        assert response.status_code == 200
        data = response.json()
        assert "plans" in data
        assert "free" in data["plans"]
        assert "starter" in data["plans"]
        assert "pro" in data["plans"]
        assert "business" in data["plans"]
        # Each tier should have 9 fields
        assert len(data["plans"]["free"]) == 9

    def test_put_plans_updates_tiers(self, admin_client, db_session):
        """PUT /plans updates plan tier values."""
        response = admin_client.put(
            "/api/v2/admin/settings/plans",
            json={
                "plans": {
                    "free": {"credits": "50", "monthly_quota": "50"},
                }
            },
        )
        assert response.status_code == 200

        # Verify persisted
        from app.services.platform_settings_service import PlatformSettingsService

        val = PlatformSettingsService.get(db_session, "plan_free_credits")
        assert val == "50"


class TestSettingsNonAdminAccess:
    """ADMIN-01/02/03/04: Non-admin users get 403."""

    def test_non_admin_registry_403(self, authenticated_client):
        """Non-admin gets 403 on registry endpoint."""
        response = authenticated_client.get("/api/v2/admin/settings/registry")
        assert response.status_code == 403

    def test_non_admin_values_403(self, authenticated_client):
        """Non-admin gets 403 on values endpoint."""
        response = authenticated_client.get("/api/v2/admin/settings/values")
        assert response.status_code == 403

    def test_non_admin_update_403(self, authenticated_client):
        """Non-admin gets 403 on update endpoint."""
        response = authenticated_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"SOLVER_DEFAULT_TIMEOUT": "120"}},
        )
        assert response.status_code == 403


class TestSettingsFullFlow:
    """Integration: Full set -> verify -> audit -> reset flow."""

    def test_full_flow(self, admin_client, db_session):
        """Set a value, verify it, check audit, reset, verify reverted."""
        # 1. Set
        resp = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"SOLVER_POOL_SIZE": "16"}},
        )
        assert resp.status_code == 200
        assert "SOLVER_POOL_SIZE" in resp.json()["updated"]

        # 2. Verify value reflected
        resp = admin_client.get("/api/v2/admin/settings/values?category=solver")
        assert resp.status_code == 200
        assert resp.json()["settings"]["SOLVER_POOL_SIZE"]["value"] == "16"
        assert resp.json()["settings"]["SOLVER_POOL_SIZE"]["is_modified"] is True

        # 3. Check audit
        resp = admin_client.get("/api/v2/admin/settings/audit?category=solver")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # 4. Reset
        resp = admin_client.post("/api/v2/admin/settings/reset/SOLVER_POOL_SIZE")
        assert resp.status_code == 200

        # 5. Verify reverted (no longer modified)
        resp = admin_client.get("/api/v2/admin/settings/values?category=solver")
        assert resp.status_code == 200
        assert resp.json()["settings"]["SOLVER_POOL_SIZE"]["is_modified"] is False

        # 6. Check audit has reset entry (new_value = registry default)
        from app.services.settings_registry import REGISTRY_BY_KEY

        registry_default = REGISTRY_BY_KEY["SOLVER_POOL_SIZE"].default_value
        resp = admin_client.get(
            "/api/v2/admin/settings/audit?category=solver",
        )
        audit_items = resp.json()["items"]
        reset_entries = [
            i
            for i in audit_items
            if i["setting_key"] == "SOLVER_POOL_SIZE" and i["new_value"] == registry_default
        ]
        assert len(reset_entries) >= 1
