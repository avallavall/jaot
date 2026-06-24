"""Internal pytest helpers — NOT auto-collected by pytest.

The `_` prefix on the directory excludes it from pytest's default test
collection. Modules named `test_*.py` inside this package are still
collected (e.g. `test_anti_oracle.py` is the unit-test suite for the
helper exported here).

See:
    - tests/test_quality_proof.md (Tier-1 anti-patterns enforced by
      scripts/check_test_quality_tier1.py — helpers are NOT exempt)
"""
