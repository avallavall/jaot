"""Validate ALL catalog templates: example_input → generate → solve.

Runs every template's example_input through the generator and solver,
reports failures. Ensures no template ships with a broken example.

Usage:
    python scripts/validate_all_templates.py

In Docker:
    docker compose -f deploy/docker-compose.prod.yml --env-file .env.production \
        run --rm -v /opt/jaot/scripts:/app/scripts api python scripts/validate_all_templates.py
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.data.templates import load_all_templates  # noqa: E402
from app.domains.solver.services.solver_service import SolverService  # noqa: E402
from app.domains.solver.services.template_engine import TemplateEngine  # noqa: E402


def validate_all() -> None:
    templates = load_all_templates()
    engine = TemplateEngine()
    solver = SolverService()

    print(f"\nValidating {len(templates)} templates...\n")

    passed: list[tuple[str, str, float | None, float]] = []
    failed: list[tuple[str, str, str]] = []
    skipped: list[tuple[str, str]] = []

    for tmpl in templates:
        tid = tmpl.id if hasattr(tmpl, "id") else tmpl.get("id", "?")
        example = (
            tmpl.example_input if hasattr(tmpl, "example_input") else tmpl.get("example_input")
        )

        # Engine expects "generator" key; map from legacy "generator_type".
        tmpl_dict = tmpl.model_dump() if hasattr(tmpl, "model_dump") else dict(tmpl)
        if "generator_type" in tmpl_dict and "generator" not in tmpl_dict:
            tmpl_dict["generator"] = tmpl_dict["generator_type"]

        if not example:
            skipped.append((tid, "no example_input"))
            print(f"  SKIP  {tid} — no example_input")
            continue

        example_dict = (
            example.model_dump()
            if hasattr(example, "model_dump")
            else dict(example)
            if not isinstance(example, dict)
            else example
        )

        try:
            start = time.time()

            problem = engine.render(tmpl_dict, example_dict)
            result = solver.solve(problem)
            elapsed = time.time() - start

            status = result.status if hasattr(result, "status") else result.get("status", "unknown")
            obj = (
                result.objective_value
                if hasattr(result, "objective_value")
                else result.get("objective_value")
            )

            status_str = str(status)
            if "optimal" in status_str.lower() or (
                "feasible" in status_str.lower() and "infeasible" not in status_str.lower()
            ):
                passed.append((tid, status_str, obj, elapsed))
                print(f"  PASS  {tid} — {status_str}, obj={obj}, {elapsed:.2f}s")
            else:
                err = (
                    result.error_message
                    if hasattr(result, "error_message")
                    else result.get("error_message", "")
                )
                failed.append((tid, f"status={status_str}", str(err)))
                print(f"  FAIL  {tid} — status={status_str} error={err}")

        except Exception as e:
            elapsed = time.time() - start
            failed.append((tid, "exception", str(e)))
            print(f"  FAIL  {tid} — {type(e).__name__}: {e}")
            if "--verbose" in sys.argv:
                traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped")
    print(f"{'=' * 60}")

    if failed:
        print("\nFAILED TEMPLATES:")
        for tid, reason, detail in failed:
            detail_short = detail[:200] if len(detail) > 200 else detail
            print(f"  ✗ {tid}: {reason} — {detail_short}")
        print(f"\n{len(failed)} templates have broken example_input!")
        sys.exit(1)
    else:
        print("\nAll templates with example_input executed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    validate_all()
