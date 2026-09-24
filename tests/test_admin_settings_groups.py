"""Every setting in the admin panel sits under a named group.

The settings tab groups entries by the ``SETTING_GROUPS`` map in
``frontend/src/components/admin/settings/SettingsTab.tsx``. A key missing from
that map fell back to the first two words of its own name, so the panel showed
headings such as "AUTH MAX" and "APP VERSION" (found driving the admin panel,
2026-09-24). The map also kept ``JAOT_DSL`` long after that flag was removed.

This test reads the map and compares it with ``SETTINGS_REGISTRY``.

# CONTRACT-TEST: every non-secret setting has an explicit admin group, and the
# group map names no setting that does not exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.settings_registry import SETTINGS_REGISTRY, SettingCategory

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TS_FILE = _REPO_ROOT / "frontend" / "src" / "components" / "admin" / "settings" / "SettingsTab.tsx"

#: Rendered by the secrets tab, which lists them without groups.
_UNGROUPED = {SettingCategory.SECRETS.value}


def _group_map() -> dict[str, set[str]]:
    """``{category: {key, ...}}`` from the ``SETTING_GROUPS`` object literal."""
    if not _TS_FILE.exists():
        pytest.fail(f"SettingsTab.tsx not found at {_TS_FILE}")
    src = _TS_FILE.read_text(encoding="utf-8")
    start = src.index("const SETTING_GROUPS")
    body = src[start : src.index("\n};", start)]
    groups: dict[str, set[str]] = {}
    category = None
    for line in body.splitlines():
        opened = re.match(r"^  ([a-z_]+): \{", line)
        if opened:
            category = opened.group(1)
            groups[category] = set()
            continue
        entry = re.match(r'^\s+([A-Za-z0-9_]+): "', line)
        if entry and category is not None:
            groups[category].add(entry.group(1))
    return groups


def _registry() -> dict[str, set[str]]:
    by_category: dict[str, set[str]] = {}
    for entry in SETTINGS_REGISTRY:
        category = getattr(entry.category, "value", entry.category)
        by_category.setdefault(category, set()).add(entry.key)
    return by_category


def test_every_setting_has_a_named_group() -> None:
    groups = _group_map()
    missing = sorted(
        f"{category}.{key}"
        for category, keys in _registry().items()
        if category not in _UNGROUPED
        for key in keys
        if key not in groups.get(category, set())
    )
    assert missing == [], f"settings with no group in SettingsTab.tsx: {missing}"


def test_the_group_map_names_only_real_settings() -> None:
    registry = _registry()
    stale = sorted(
        f"{category}.{key}"
        for category, keys in _group_map().items()
        for key in keys
        if key not in registry.get(category, set())
    )
    assert stale == [], f"SettingsTab.tsx groups settings that do not exist: {stale}"
