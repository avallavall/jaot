"""Regression tests for scripts/ensure_admin_api_key.py (DEPLOY-05).

The script previously eager-evaluated `settings.API_KEY_DEFAULT_PREFIX`, which
does not exist on the Settings object (it is a PSS DB setting, not an infra
config var). Import itself raised AttributeError before any env-var override
could take effect. This test pins the lazy-evaluation fix per D-08.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPT_MODULE = "scripts.ensure_admin_api_key"


def _reload_script(monkeypatch, env: dict[str, str]) -> object:
    # Ensure project root is importable
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    # Clear cached module
    sys.modules.pop(SCRIPT_MODULE, None)
    # Clear the env vars we may override so monkeypatch wins deterministically
    for key in ("ENSURE_ADMIN_KEY_PREFIX",):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.import_module(SCRIPT_MODULE)


@pytest.mark.unit
def test_import_does_not_raise_without_env_override(monkeypatch):
    """Importing the script must succeed even if Settings has no API_KEY_DEFAULT_PREFIX."""
    mod = _reload_script(monkeypatch, env={})
    # The module-level constant must resolve to the hardcoded fallback.
    assert mod.ADMIN_KEY_PREFIX == "ok_live_"


@pytest.mark.unit
def test_env_override_takes_precedence(monkeypatch):
    mod = _reload_script(monkeypatch, env={"ENSURE_ADMIN_KEY_PREFIX": "custom_"})
    assert mod.ADMIN_KEY_PREFIX == "custom_"


@pytest.mark.unit
def test_empty_env_falls_back(monkeypatch):
    """Explicit empty string is also a falsy override — should fall back."""
    mod = _reload_script(monkeypatch, env={"ENSURE_ADMIN_KEY_PREFIX": ""})
    assert mod.ADMIN_KEY_PREFIX == "ok_live_"
