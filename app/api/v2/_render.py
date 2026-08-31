"""Turn a generator's refusal into a 422 instead of a 500.

The generators package raises ``ValueError`` for bad input, and this release
took that from 36 raise sites to 113 across 30 files. Three of the five HTTP
call sites of ``TemplateEngine.render`` had no ``try`` at all, and the app
registers no ``ValueError`` handler, so a card whose input a user got wrong
answered 500. The two sites that did guard disagreed on the code (400 and 422)
for the same exception. One helper, one code, no drift.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.domains.solver.services.template_engine import TemplateEngine
from app.schemas.optimization import OptimizationProblem


def render_or_422(
    engine: TemplateEngine,
    template: dict[str, Any],
    input_data: dict[str, Any],
) -> OptimizationProblem:
    """Render *template* with *input_data*, mapping any build failure to 422."""
    try:
        return engine.render(template, input_data)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — any generator failure → 422, not 500
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not build a model from this template: {exc}",
        ) from exc
