"""Shared fixtures for solver domain unit tests.

Provides test isolation for SolverRegistry per D-10: every test gets a clean
registry so cross-test pollution (e.g. one test registering a fake adapter
that leaks into another) cannot happen.

NOTE (Phase 7.1 / D-7.1-14): this autouse fixture is intentionally scoped to
``tests/unit/domains/solver/`` via its conftest location. pytest DOES NOT
propagate autouse fixtures into sibling directories (e.g.
``tests/integration/api/v2/``), so integration tests are not affected by the
setup/teardown reset() calls below DURING their own execution.

HOWEVER, when BOTH suites run in the same pytest invocation, the LAST unit
test's teardown still wipes the registry — the process-global singleton is
shared. The corresponding guard is in
``tests/integration/api/v2/conftest.py::_ensure_default_adapters_registered``,
which re-invokes the idempotent ``register_default_adapters()`` before each
integration test that needs the registry.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_solver_registry() -> None:
    """Reset the solver registry before each test.

    Imported lazily inside the fixture so tests that do NOT need the registry
    (e.g. test_solver_capabilities.py) still run even before registry.py exists.
    """
    try:
        from app.domains.solver.adapters import registry

        registry.reset()
    except ImportError:
        pass
    yield
    try:
        from app.domains.solver.adapters import registry

        registry.reset()
    except ImportError:
        pass


@pytest.fixture
def make_lic_file(tmp_path: Path) -> Callable[..., Path]:
    """Factory: write a fake .lic file into ``tmp_path`` and return its path.

    Phase 7.4 / D-01 made ``HexalyAdapter.__init__`` fail-fast when
    ``/etc/jaot/hexaly.lic`` is absent or already-expired. Most contract
    tests want a parseable file so they can exercise the post-init code.
    The default expires 2099-12-31 — comfortably future for any reasonable
    suite run.

    Tests pair this with a ``monkeypatch.setattr`` of
    ``app.domains.solver.adapters.hexaly.HEXALY_LIC_PATH`` (and the same
    constant in the expiry-sweep task module when applicable).
    """

    def _make(expires: str = "2099-12-31") -> Path:
        lic = tmp_path / "hexaly.lic"
        lic.write_text(f"EXPIRES={expires}\nFAKE_HEXALY_BLOB_FOR_UNIT_TESTS\n")
        return lic

    return _make
