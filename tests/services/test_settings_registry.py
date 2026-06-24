"""Phase 7.4 / PRC-01 — pricing.solver_multiplier.{scip,highs,hexaly} keys present."""

from __future__ import annotations


class TestPricingMultiplierKeys:
    def test_pricing_multiplier_keys_registered(self) -> None:
        """V-09: 3 PSS keys present with FLOAT type and defaults 1.0/1.2/5.0.
        (Phase 7.4 / Plan 04 Task 1)"""
        from app.services.settings_registry import (
            SETTINGS_REGISTRY,
            SettingType,
        )

        by_key = {s.key: s for s in SETTINGS_REGISTRY}
        for solver, default in [("scip", "1.0"), ("highs", "1.2"), ("hexaly", "5.0")]:
            key = f"pricing.solver_multiplier.{solver}"
            assert key in by_key, f"missing {key}"
            entry = by_key[key]
            assert entry.setting_type == SettingType.FLOAT
            assert entry.default_value == default
