"""Platform settings service for runtime admin configuration.

Provides typed accessors for platform-wide settings stored in the
platform_settings table.

Fallback chain: DB row -> registry default_value -> MissingSettingError.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from app.models.platform_setting import PlatformSetting
from app.models.platform_setting_audit import PlatformSettingAudit
from app.services.settings_registry import (
    REGISTRY_BY_KEY,
    SettingType,
)

logger = logging.getLogger(__name__)

_SENTINEL = object()


class MissingSettingError(RuntimeError):
    """A required platform setting is missing from the database."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"Platform setting '{key}' not found in database. "
            f"Run 'alembic upgrade head' to seed default values."
        )
        self.key = key


class PlatformSettingsService:
    """Service to read/write platform settings."""

    @classmethod
    def get(cls, db: Session, key: str) -> str:
        """Get a platform setting value.

        Fallback chain:
            1. DB row (normal case after seed migration)
            2. Registry ``default_value`` (safety net if seed is missing)
            3. Raise ``MissingSettingError``

        Args:
            db: Database session.
            key: Setting key.

        Returns:
            Setting value as string.

        Raises:
            MissingSettingError: If the key is not in the DB or registry.
        """
        setting = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
        if setting:
            return setting.value

        # Safety net: fall back to registry default_value
        definition = REGISTRY_BY_KEY.get(key)
        if definition is not None and definition.default_value is not None:
            logger.warning(
                "Setting '%s' not in DB — falling back to registry "
                "default. Run 'alembic upgrade head' to seed.",
                key,
            )
            return definition.default_value

        raise MissingSettingError(key)

    @classmethod
    def get_many(cls, db: Session, keys: list[str]) -> dict[str, str]:
        """Batch-fetch multiple settings in a single DB query.

        Returns a dict of key -> value. Falls back to registry defaults
        for keys not found in the DB, same as get().
        """
        rows = db.query(PlatformSetting).filter(PlatformSetting.key.in_(keys)).all()
        result = {row.key: row.value for row in rows}

        # Fill missing keys from registry defaults
        for key in keys:
            if key not in result:
                definition = REGISTRY_BY_KEY.get(key)
                if definition is not None and definition.default_value is not None:
                    result[key] = definition.default_value

        return result

    @classmethod
    def set(
        cls, db: Session, key: str, value: str, updated_by: str | None = None
    ) -> PlatformSetting:
        """Create or update a platform setting.

        Args:
            db: Database session.
            key: Setting key.
            value: Setting value.
            updated_by: User ID who made the change.

        Returns:
            The created or updated PlatformSetting.
        """
        setting = db.query(PlatformSetting).filter(PlatformSetting.key == key).first()
        if setting:
            setting.value = value
            setting.updated_by = updated_by
        else:
            setting = PlatformSetting(key=key, value=value, updated_by=updated_by)
            db.add(setting)
        db.flush()
        return setting

    @classmethod
    def get_int(
        cls,
        db: Session,
        key: str,
        default: object = _SENTINEL,
    ) -> int:
        """Get a platform setting as an integer.

        Args:
            db: Database session.
            key: Setting key.
            default: *Deprecated* — kept for backward compat during
                transition. Callers should stop passing this.

        Returns:
            Integer value.

        Raises:
            ValueError: If the stored value cannot be parsed as int.
        """
        val = cls.get(db, key)
        try:
            return int(val) if val else (default if default is not _SENTINEL else 0)
        except (ValueError, TypeError) as exc:
            if default is not _SENTINEL:
                return int(default)  # type: ignore[arg-type]
            raise ValueError(f"Setting '{key}' has non-integer value '{val}'") from exc

    @classmethod
    def get_float(
        cls,
        db: Session,
        key: str,
        default: object = _SENTINEL,
    ) -> float:
        """Get a platform setting as a float.

        Args:
            db: Database session.
            key: Setting key.
            default: *Deprecated* — kept for backward compat.

        Returns:
            Float value.

        Raises:
            ValueError: If the stored value cannot be parsed as float.
        """
        val = cls.get(db, key)
        try:
            return float(val) if val else (default if default is not _SENTINEL else 0.0)
        except (ValueError, TypeError) as exc:
            if default is not _SENTINEL:
                return float(default)  # type: ignore[arg-type]
            raise ValueError(f"Setting '{key}' has non-float value '{val}'") from exc

    @classmethod
    def get_bool(
        cls,
        db: Session,
        key: str,
        default: object = _SENTINEL,
    ) -> bool:
        """Get a platform setting as a boolean.

        Args:
            db: Database session.
            key: Setting key.
            default: *Deprecated* — kept for backward compat.

        Returns:
            Boolean value.
        """
        val = cls.get(db, key)
        if not val:
            return default if default is not _SENTINEL else False  # type: ignore[return-value]
        return val.lower() in ("true", "1", "yes")

    @classmethod
    def get_str(
        cls,
        db: Session,
        key: str,
        default: object = _SENTINEL,
    ) -> str:
        """Get a platform setting as a string.

        Args:
            db: Database session.
            key: Setting key.
            default: *Deprecated* — kept for backward compat.

        Returns:
            String value.
        """
        val = cls.get(db, key)
        return (
            val
            if val
            else (
                default if default is not _SENTINEL else ""  # type: ignore[return-value]
            )
        )

    @classmethod
    def get_plan_config_dynamic(cls, db: Session, plan_name: str) -> dict[str, Any]:
        """Get plan configuration from DB for a given plan name.

        Returns a dict with keys: credits, monthly_quota, rate_limit_per_minute,
        rate_limit_per_day, max_solve_time_seconds, max_variables,
        max_daily_solves, max_cron_schedules, allowed_features.

        Falls back to registry defaults via the standard get() chain.

        Args:
            db: Database session.
            plan_name: Plan name (e.g. "free", "starter").

        Returns:
            Dict of plan configuration values.
        """
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
        plan_key = (plan_name or cls.get_str(db, "DEFAULT_PLAN", "free")).lower()

        _known_tiers = {"free", "starter", "pro", "business"}
        if plan_key not in _known_tiers:
            logger.warning(
                "Unknown plan '%s', falling back to 'free'",
                plan_key,
            )
            plan_key = "free"

        # Batch-fetch all plan fields in a single DB query
        db_keys = [f"plan_{plan_key}_{field}" for field in fields]
        raw_values = cls.get_many(db, db_keys)

        result: dict[str, Any] = {}
        for field in fields:
            key = f"plan_{plan_key}_{field}"
            raw = raw_values.get(key, "")
            if field == "allowed_features":
                try:
                    result[field] = json.loads(raw) if raw else []
                except (ValueError, TypeError):
                    result[field] = []
            else:
                try:
                    result[field] = int(raw) if raw else 0
                except (ValueError, TypeError):
                    result[field] = 0
        return result

    @classmethod
    def validate_value(cls, key: str, value: str) -> tuple[bool, str | None]:
        """Validate a value against registry constraints.

        Args:
            key: Setting key.
            value: Value to validate.

        Returns:
            Tuple of (is_valid, error_message). error_message is None if valid.
        """
        definition = REGISTRY_BY_KEY.get(key)
        if definition is None:
            return False, f"Unknown setting key: {key}"

        if definition.is_readonly:
            return False, f"Setting '{key}' is read-only"

        stype = definition.setting_type

        if stype == SettingType.INT:
            try:
                num = int(value)
            except (ValueError, TypeError):
                return False, f"Expected integer for '{key}', got '{value}'"
            if definition.min_value is not None and num < definition.min_value:
                return False, (
                    f"Value {num} is below minimum {int(definition.min_value)} for '{key}'"
                )
            if definition.max_value is not None and num > definition.max_value:
                return False, (
                    f"Value {num} exceeds maximum {int(definition.max_value)} for '{key}'"
                )

        elif stype == SettingType.FLOAT:
            try:
                num = float(value)
            except (ValueError, TypeError):
                return False, f"Expected number for '{key}', got '{value}'"
            if definition.min_value is not None and num < definition.min_value:
                return False, (f"Value {num} is below minimum {definition.min_value} for '{key}'")
            if definition.max_value is not None and num > definition.max_value:
                return False, (f"Value {num} exceeds maximum {definition.max_value} for '{key}'")

        elif stype == SettingType.BOOL:
            if value.lower() not in ("true", "false", "1", "0"):
                return False, (f"Expected boolean for '{key}', got '{value}'")

        elif stype == SettingType.JSON:
            try:
                json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return False, f"Expected valid JSON for '{key}', got '{value}'"

        # STRING type: no validation needed beyond presence

        return True, None

    @classmethod
    def bulk_set(
        cls,
        db: Session,
        updates: dict[str, str],
        changed_by: str,
    ) -> list[PlatformSettingAudit]:
        """Update multiple settings with audit logging.

        Skips readonly keys and unchanged values. Flushes but does NOT commit
        (caller-commits pattern).

        Args:
            db: Database session.
            updates: Key-value pairs to update.
            changed_by: Admin user email/ID.

        Returns:
            List of audit records created.
        """
        audits: list[PlatformSettingAudit] = []

        for key, new_value in updates.items():
            definition = REGISTRY_BY_KEY.get(key)
            if not definition or definition.is_readonly:
                continue

            old_value = cls.get(db, key)
            if str(old_value) == str(new_value):
                continue  # No change

            cls.set(db, key, new_value, updated_by=changed_by)

            audit = PlatformSettingAudit(
                setting_key=key,
                old_value=old_value if old_value else None,
                new_value=new_value,
                changed_by=changed_by,
                category=definition.category.value if definition.category else None,
            )
            db.add(audit)
            audits.append(audit)

        db.flush()
        return audits

    @classmethod
    def reset_to_default(
        cls,
        db: Session,
        key: str,
        changed_by: str,
    ) -> PlatformSettingAudit | None:
        """Reset a setting to its registry default value.

        Writes the registry ``default_value`` back to the DB row (never
        deletes it), so the row always exists for future reads.

        Args:
            db: Database session.
            key: Setting key to reset.
            changed_by: Admin user email/ID.

        Returns:
            Audit record, or None if key not found or is readonly.
        """
        definition = REGISTRY_BY_KEY.get(key)
        if not definition or definition.is_readonly:
            return None

        default = definition.default_value or ""
        old_value = cls.get(db, key)

        # Write registry default back to DB
        cls.set(db, key, default, updated_by=changed_by)

        audit = PlatformSettingAudit(
            setting_key=key,
            old_value=old_value if old_value else None,
            new_value=default,
            changed_by=changed_by,
            category=(definition.category.value if definition.category else None),
        )
        db.add(audit)
        db.flush()
        return audit

    @classmethod
    def get_all_values(cls, db: Session) -> dict[str, dict]:
        """Return all setting values with metadata.

        For secret keys, the value is masked as ``"****"`` if non-empty.

        Returns:
            Dict of key -> {value, default_value, is_modified,
            last_changed_by, last_changed_at}.
        """
        result: dict[str, dict] = {}

        # Preload all DB rows
        db_rows: dict[str, PlatformSetting] = {
            row.key: row for row in db.query(PlatformSetting).all()
        }

        for definition in REGISTRY_BY_KEY.values():
            key = definition.key
            db_row = db_rows.get(key)
            registry_default = definition.default_value or ""

            if db_row:
                raw_value = db_row.value
                is_modified = raw_value != registry_default
                last_changed_by = db_row.updated_by
                last_changed_at = db_row.updated_at.isoformat() if db_row.updated_at else None
            else:
                raw_value = registry_default
                is_modified = False
                last_changed_by = None
                last_changed_at = None

            # Mask secrets and detect env var source
            if definition.is_secret:
                env_val = os.environ.get(key, "")
                has_db_value = bool(raw_value)
                has_env_value = bool(env_val)
                display_value = "****" if (has_db_value or has_env_value) else ""
                source = "db" if has_db_value else ("env" if has_env_value else "none")
            else:
                display_value = raw_value
                source = "db" if db_row else "default"

            result[key] = {
                "value": display_value,
                "default_value": registry_default,
                "is_modified": is_modified,
                "last_changed_by": last_changed_by,
                "last_changed_at": last_changed_at,
                "source": source,
            }

        return result

    @classmethod
    def get_plan_tiers(cls, db: Session) -> dict[str, dict[str, str]]:
        """Return plan configs grouped by tier name.

        Returns:
            Dict of tier_name -> {field: value} for all 4 tiers x 9 fields.
        """
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

        result: dict[str, dict[str, str]] = {}
        for tier in tiers:
            tier_data: dict[str, str] = {}
            for field in fields:
                key = f"plan_{tier}_{field}"
                tier_data[field] = cls.get(db, key)
            result[tier] = tier_data
        return result

    @classmethod
    def set_plan_tiers(
        cls,
        db: Session,
        plans: dict[str, dict[str, str]],
        changed_by: str,
    ) -> list[PlatformSettingAudit]:
        """Batch-update plan tier settings.

        Args:
            db: Database session.
            plans: Dict of tier_name -> {field: value}.
            changed_by: Admin user email/ID.

        Returns:
            List of audit records created.
        """
        updates: dict[str, str] = {}
        for tier, fields in plans.items():
            for field, value in fields.items():
                key = f"plan_{tier}_{field}"
                if key in REGISTRY_BY_KEY:
                    updates[key] = value

        return cls.bulk_set(db, updates, changed_by)

    @classmethod
    def get_commission_rate(cls, db: Session) -> float:
        """Get the marketplace commission rate as a float.

        Returns:
            Commission rate (e.g. 0.10 for 10%). Defaults to 0.10.
        """
        return float(cls.get(db, "marketplace_commission_rate"))
