"""Tests for the settings registry.

Validates that:
- Every non-secret registry entry has a non-None default_value.
- All default_value strings can be parsed to their declared setting_type.
- No duplicate keys exist in the registry.
"""

from __future__ import annotations

import json

import pytest

from app.services.settings_registry import (
    REGISTRY_BY_KEY,
    SETTINGS_REGISTRY,
    SettingType,
)


class TestSettingsRegistryDefaults:
    """Ensure every non-secret entry has a parseable default_value."""

    def test_non_secret_entries_have_default_value(self) -> None:
        """Every non-secret registry entry must have a non-None default_value."""
        missing: list[str] = []
        for defn in SETTINGS_REGISTRY:
            if defn.is_secret:
                continue
            if defn.default_value is None:
                missing.append(defn.key)
        assert missing == [], f"Non-secret registry entries missing default_value: {missing}"

    @pytest.mark.parametrize(
        "defn",
        [d for d in SETTINGS_REGISTRY if d.default_value is not None],
        ids=lambda d: d.key,
    )
    def test_default_value_parseable(self, defn) -> None:
        """Each default_value must parse to its declared setting_type."""
        val = defn.default_value
        stype = defn.setting_type

        if stype == SettingType.INT:
            parsed = int(val)
            assert isinstance(parsed, int)
        elif stype == SettingType.FLOAT:
            parsed = float(val)
            assert isinstance(parsed, float)
        elif stype == SettingType.BOOL:
            assert val.lower() in (
                "true",
                "false",
                "1",
                "0",
            ), f"{defn.key}: bool default_value must be 'true'/'false'/'1'/'0', got '{val}'"
        elif stype == SettingType.JSON:
            parsed = json.loads(val)
            assert parsed is not None
        elif stype == SettingType.STRING:
            # Any string is valid, including empty string
            assert isinstance(val, str)

    def test_no_duplicate_keys(self) -> None:
        """Registry must not contain duplicate keys."""
        seen: set[str] = set()
        dupes: list[str] = []
        for defn in SETTINGS_REGISTRY:
            if defn.key in seen:
                dupes.append(defn.key)
            seen.add(defn.key)
        assert dupes == [], f"Duplicate registry keys: {dupes}"

    def test_registry_by_key_matches_list(self) -> None:
        """REGISTRY_BY_KEY must contain all entries from SETTINGS_REGISTRY."""
        list_keys = {d.key for d in SETTINGS_REGISTRY}
        dict_keys = set(REGISTRY_BY_KEY.keys())
        assert list_keys == dict_keys

    def test_default_value_within_bounds(self) -> None:
        """Numeric default_values must respect min_value/max_value."""
        violations: list[str] = []
        for defn in SETTINGS_REGISTRY:
            if defn.default_value is None:
                continue
            if defn.default_value == "":
                continue

            if defn.setting_type == SettingType.INT:
                try:
                    num = int(defn.default_value)
                except ValueError:
                    continue
                if defn.min_value is not None and num < defn.min_value:
                    violations.append(f"{defn.key}: {num} < min {defn.min_value}")
                if defn.max_value is not None and num > defn.max_value:
                    violations.append(f"{defn.key}: {num} > max {defn.max_value}")
            elif defn.setting_type == SettingType.FLOAT:
                try:
                    num_f = float(defn.default_value)
                except ValueError:
                    continue
                if defn.min_value is not None and num_f < defn.min_value:
                    violations.append(f"{defn.key}: {num_f} < min {defn.min_value}")
                if defn.max_value is not None and num_f > defn.max_value:
                    violations.append(f"{defn.key}: {num_f} > max {defn.max_value}")
        assert violations == [], f"Default values out of bounds: {violations}"
