"""Tests for admin settings API — registry, service, and CRUD endpoints.

Covers requirements: ADMIN-01, ADMIN-02, ADMIN-03, ADMIN-04.
"""

import re
from pathlib import Path

from app.models.platform_setting import PlatformSetting

_APP_DIR = Path(__file__).resolve().parents[2] / "app"
_REGISTRY_FILE = _APP_DIR / "services" / "settings_registry.py"

# Keys whose reader builds the name at runtime, so no source file contains the
# literal. Each entry names the reader that must keep existing — an f-string
# that stops matching is a real break, and the assertion below catches it.
_DYNAMIC_READERS: dict[str, tuple[str, str]] = {
    "HOME_ANNOUNCEMENT_TEXT_": ("api/v2/home.py", 'f"HOME_ANNOUNCEMENT_TEXT_{locale.upper()}"'),
    "instance_": ("services/platform_settings_service.py", 'f"instance_{field}"'),
}


def _app_sources() -> dict[Path, str]:
    """Every backend source file except the registry that declares the settings."""
    return {
        path: path.read_text(encoding="utf-8")
        for path in _APP_DIR.rglob("*.py")
        if path != _REGISTRY_FILE
    }


def _quoted_names(sources: dict[Path, str]) -> set[str]:
    """Every string literal in the backend that could name a setting.

    A setting is always referenced by its NAME — passed to a PSS accessor
    directly, or collected in a list of keys the module fetches in one go
    (``email_service`` and the LLM cost tracker both do that). What it is never
    referenced as is a Python identifier, and that distinction is the whole
    point: `from app.version import APP_VERSION` used to vouch for a SETTING of
    the same name that nothing loaded.
    """
    names: set[str] = set()
    for text in sources.values():
        names |= set(re.findall(r'"([A-Za-z][A-Za-z0-9_]{2,})"', text))
        names |= set(re.findall(r"'([A-Za-z][A-Za-z0-9_]{2,})'", text))
    return names


class TestSettingsRegistry:
    """Test the settings registry data structure."""

    def test_registry_has_all_categories(self):
        """ADMIN-01: Registry covers the core categories."""
        from app.services.settings_registry import REGISTRY_BY_CATEGORY, SettingCategory

        expected = {
            SettingCategory.LIMITS,
            SettingCategory.SOLVER,
            SettingCategory.LLM,
            SettingCategory.EMAIL,
            SettingCategory.SECURITY,
            SettingCategory.SECRETS,
        }
        actual = set(REGISTRY_BY_CATEGORY.keys())
        assert expected.issubset(actual), f"Missing categories: {expected - actual}"

    # CONTRACT-TEST: every declared setting is read by some live code path
    def test_every_setting_has_a_runtime_reader(self):
        """A setting nobody reads is a control that does nothing when an operator turns it.

        The 1.9 panel review found 17 of them — including a gzip threshold the
        middleware hardcoded past, and a Hexaly time limit the adapter ignored
        in favour of a module constant. Each looked configurable in the admin
        panel and changed nothing at all.

        This is the check that was missing. It fails on the DECLARING side: if a
        setting is genuinely retired, delete it from the registry; if it is new,
        wire the code that reads it before shipping the control.
        """
        from app.services.settings_registry import SETTINGS_REGISTRY

        # The key must appear as a STRING, the only way a setting is ever
        # referenced. Matching the bare word let a Python constant of the same
        # name vouch for a setting nobody loads — how APP_VERSION passed while
        # `app.version.APP_VERSION` was what the code actually used.
        read_keys = _quoted_names(_app_sources())
        unread: list[str] = []

        for definition in SETTINGS_REGISTRY:
            key = definition.key
            # Read-only entries are MIRRORS of a code constant, shown in the
            # panel and refreshed at startup (see tests/test_settings_seed_race).
            # They are displayed, not loaded, so "who reads it" does not apply —
            # and they cannot mislead an operator, because nothing can be typed
            # into them.
            if definition.is_readonly:
                continue

            dynamic = next((p for p in _DYNAMIC_READERS if key.startswith(p)), None)
            if dynamic is not None:
                reader_file, reader_expr = _DYNAMIC_READERS[dynamic]
                reader = _APP_DIR / reader_file
                if reader_expr not in reader.read_text(encoding="utf-8"):
                    unread.append(f"{key} (dynamic reader {reader_expr} gone from {reader_file})")
                continue

            if key not in read_keys:
                unread.append(key)

        assert not unread, (
            "Settings declared in the registry that no backend code reads — "
            "the admin panel would offer an edit that changes nothing:\n  "
            + "\n  ".join(sorted(unread))
        )

    # CONTRACT-TEST: no category exists without settings (renders an empty tab)
    def test_every_category_has_settings(self):
        """An empty category is a tab that renders blank.

        ``marketplace`` was one for the entire life of the panel: declared in the
        enum, given a tab in the UI, and never assigned a single setting.
        """
        from app.services.settings_registry import REGISTRY_BY_CATEGORY, SettingCategory

        empty = [c.value for c in SettingCategory if not REGISTRY_BY_CATEGORY.get(c)]
        assert not empty, f"Categories with no settings (would render an empty tab): {empty}"

    # CONTRACT-TEST: the D-22 prune list never names a setting that is still live
    def test_pruned_orphan_keys_are_not_in_the_registry(self):
        """The orphan prune (D-22) deletes rows by an explicit list of keys.

        An explicit list is what keeps that migration deterministic, but it is
        also what can go wrong: a key typed into it that the registry still
        declares would delete a live setting's value, and the operator would
        find their number silently back at the shipped default after the next
        boot re-seeded it. Nothing in the migration itself can catch that — it
        runs before the app imports.
        """
        import importlib.util

        from app.services.settings_registry import SETTINGS_REGISTRY

        path = (
            Path(__file__).resolve().parents[2]
            / "infra"
            / "alembic"
            / "versions"
            / "20260728_prune_orphan_settings.py"
        )
        spec = importlib.util.spec_from_file_location("_prune_orphan_settings", path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        live = {d.key for d in SETTINGS_REGISTRY}
        collisions = sorted(live & set(migration.ORPHAN_KEYS))
        assert not collisions, (
            f"The orphan prune would delete settings the registry still declares: {collisions}"
        )
        assert len(set(migration.ORPHAN_KEYS)) == len(migration.ORPHAN_KEYS), (
            "Duplicate keys in the prune list"
        )

    def test_registry_keys_are_unique(self):
        """No key declared twice — the later one silently wins in REGISTRY_BY_KEY.

        Replaces a "registry has 88+ entries" floor. That number only ever went
        up, so it caught nothing while the panel filled with settings nobody
        read; the reader and empty-category checks above are the real guards.
        A duplicate key, on the other hand, is a live hazard: the panel would
        show two fields writing to one row.
        """
        from app.services.settings_registry import SETTINGS_REGISTRY

        keys = [d.key for d in SETTINGS_REGISTRY]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        assert not duplicates, f"Duplicate setting keys: {duplicates}"
        assert keys, "Registry is empty"

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

    def test_instance_limit_keys_exist(self):
        """One limit profile, seven fields — the four tiers are gone."""
        from app.services.platform_settings_service import PlatformSettingsService as PSS
        from app.services.settings_registry import REGISTRY_BY_KEY

        for field in PSS.INSTANCE_LIMIT_FIELDS:
            key = f"instance_{field}"
            assert key in REGISTRY_BY_KEY, f"Missing instance limit: {key}"

        leftover = [k for k in REGISTRY_BY_KEY if k.startswith("plan_")]
        assert not leftover, f"Plan tier settings still declared: {leftover}"


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

        value = PlatformSettingsService.get(db_session, "LLM_MONTHLY_BUDGET_EUR")
        assert value == "50.0"


class TestPlatformSettingsServiceBulkSet:
    """ADMIN-02 + ADMIN-03: Bulk set with audit."""

    # CONTRACT-TEST: editing the instance rate limit reaches existing organizations
    def test_rate_limit_change_reaches_organizations_that_inherit_it(
        self, db_session, test_organization
    ):
        """Changing the limit in the panel must change what existing orgs get.

        These two limits are enforced from a column on `organizations`, copied
        at signup. Editing the setting therefore used to change what NEW
        organizations would receive and nothing about the ones already there —
        the panel looked like it worked and did not.

        An organization that was never given a limit of its own follows the new
        value; one an operator set deliberately keeps theirs.
        """
        from app.models.organization import Organization
        from app.services.platform_settings_service import PlatformSettingsService as PSS
        from app.shared.utils.id_generator import generate_id

        instance_value = int(PSS.get(db_session, "instance_rate_limit_per_minute"))
        test_organization.rate_limit_per_minute = instance_value  # inherited

        customised = Organization(
            id=generate_id("org_"),
            name="Deliberately throttled",
            plan="free",
            rate_limit_per_minute=7,  # an operator's own decision
            rate_limit_per_day=1000,
        )
        db_session.add(customised)
        db_session.flush()

        PSS.bulk_set(
            db_session,
            {"instance_rate_limit_per_minute": str(instance_value + 55)},
            changed_by="admin@test.com",
        )
        db_session.flush()

        db_session.refresh(test_organization)
        db_session.refresh(customised)
        assert test_organization.rate_limit_per_minute == instance_value + 55
        assert customised.rate_limit_per_minute == 7, (
            "A per-organization limit an operator set must survive an instance-wide change"
        )

        # Reset is the other write path into the same setting, and must behave
        # the same — otherwise "save" and "reset to default" would disagree
        # about what the panel means.
        PSS.reset_to_default(db_session, "instance_rate_limit_per_minute", "admin@test.com")
        db_session.flush()
        db_session.refresh(test_organization)
        db_session.refresh(customised)
        assert test_organization.rate_limit_per_minute == instance_value
        assert customised.rate_limit_per_minute == 7

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
            "ANTHROPIC_API_KEY": "sk-ant-rotated-in-the-panel",
            "SOLVER_DEFAULT_TIMEOUT": "120",
        }
        audits = PlatformSettingsService.bulk_set(db_session, updates, changed_by="admin@test.com")
        db_session.flush()

        audit_keys = {a.setting_key for a in audits}
        # Both should be updated since secrets are no longer readonly
        assert "ANTHROPIC_API_KEY" in audit_keys
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
        """EVERY secret is masked, never just the one the test happened to name.

        The previous version guarded on `if "DATABASE_URL" in settings` and
        asserted nothing when it was absent — so removing that key from the
        registry would have left the masking of the remaining secrets, the
        Anthropic key among them, completely unverified.
        """
        from app.services.settings_registry import REGISTRY_BY_CATEGORY, SettingCategory

        response = admin_client.get("/api/v2/admin/settings/values")
        assert response.status_code == 200, response.text
        settings = response.json()["settings"]

        secret_keys = [s.key for s in REGISTRY_BY_CATEGORY[SettingCategory.SECRETS]]
        assert secret_keys, "No secrets in the registry — this test would prove nothing"

        for key in secret_keys:
            assert key in settings, f"Secret {key} missing from the values response"
            value = settings[key]["value"]
            assert value in ("****", ""), f"Secret {key} served in the clear: {value}"

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


class TestInstanceLimits:
    """The four plan tiers collapsed into one instance profile (1.9 review)."""

    def test_limits_are_editable_through_the_normal_values_endpoint(self, admin_client, db_session):
        """No dedicated /plans endpoint any more — they are ordinary settings.

        This is what removes the duplication: the tier table and the loose
        fields rendered the same 28 keys on one tab, with two editors that
        wrote through different endpoints.
        """
        response = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"instance_rate_limit_per_minute": "240"}},
        )
        assert response.status_code == 200, response.text
        assert "instance_rate_limit_per_minute" in response.json()["updated"]

        from app.services.platform_settings_service import PlatformSettingsService

        assert PlatformSettingsService.get(db_session, "instance_rate_limit_per_minute") == "240"

    def test_plans_endpoint_is_gone(self, admin_client):
        """The tier endpoints left with the tiers."""
        assert admin_client.get("/api/v2/admin/settings/plans").status_code == 404

    def test_get_instance_limits_returns_every_field_typed(self, db_session):
        """All seven fields, numbers as ints and features as a list."""
        from app.services.platform_settings_service import PlatformSettingsService as PSS

        limits = PSS.get_instance_limits(db_session)

        assert set(limits) == set(PSS.INSTANCE_LIMIT_FIELDS)
        for field in PSS.INSTANCE_LIMIT_FIELDS:
            if field == "allowed_features":
                assert isinstance(limits[field], list)
            else:
                assert isinstance(limits[field], int)


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
