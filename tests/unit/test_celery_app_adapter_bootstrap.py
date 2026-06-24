"""Regression test for Phase 6.1 worker-registry bootstrap.

Context: Celery workers run `celery -A app.shared.core.celery_app worker`,
which imports `app.shared.core.celery_app` but NOT `app.main`. Before the
Phase 6.1 fix, `register_default_adapters()` was only called from
`app.main.create_app()`, so worker processes booted with an empty
`SolverRegistry` and every solve task failed at runtime with
`Solver 'scip' is not registered. Registered: []`.

The fix registers the adapters inside the solver domain's task package
init (`app/domains/solver/tasks/__init__.py`), which Celery imports when
loading task modules declared in `celery_app.conf.include`. Keeping the
bootstrap inside `app/domains/` respects the `shared-no-import-domains`
import-linter contract.

The test runs in a fresh subprocess so it mirrors what a freshly spawned
Celery worker sees: no cached imports, no pytest autouse fixtures that
reset the singleton registry between tests. This is the only reliable
way to exercise the real invariant (`import → adapters registered`).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_importing_solver_tasks_registers_adapters_in_fresh_process() -> None:
    """A fresh Python process importing `app.domains.solver.tasks` must end
    up with `scip` and `highs` registered in the solver registry. This
    mirrors the real worker-startup path."""
    script = textwrap.dedent(
        """
        import sys
        import app.domains.solver.tasks  # noqa: F401  -- imported for side effect
        from app.domains.solver.adapters import registry
        names = sorted(cap.name for cap in registry.list_available())
        print(",".join(names))
        sys.exit(0)
        """
    ).strip()
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Fresh-process bootstrap import failed. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    names = set(result.stdout.strip().split(","))
    assert "scip" in names, (
        "SolverRegistry missing 'scip' after fresh-process import of "
        "app.domains.solver.tasks. This breaks production workers silently — "
        f"see Phase 6.1 Plan 06 SUMMARY. Got: {sorted(names)}"
    )
    assert "highs" in names, (
        "SolverRegistry missing 'highs' after fresh-process import of "
        "app.domains.solver.tasks. This breaks production workers silently — "
        f"see Phase 6.1 Plan 06 SUMMARY. Got: {sorted(names)}"
    )
