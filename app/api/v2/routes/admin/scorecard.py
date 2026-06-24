"""Admin template quality scorecard endpoint.

Runs automated quality scoring on all YAML templates and returns
a detailed report with per-template scores and aggregate statistics.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services.template_scorecard import run_scorecard

router = APIRouter(prefix="/scorecard", tags=["admin-scorecard"])


@router.get("", operation_id="get_template_scorecard")
async def get_template_scorecard(
    min_score: int | None = Query(None, ge=0, le=100, description="Filter: minimum total score"),
    max_score: int | None = Query(None, ge=0, le=100, description="Filter: maximum total score"),
    grade: str | None = Query(None, description="Filter by grade: A, B, C, D, F"),
    generator_type: str | None = Query(None, description="Filter by generator type"),
    category: str | None = Query(None, description="Filter by template category"),
) -> dict[str, Any]:
    """Run quality scorecard on all templates with optional filters."""
    report = run_scorecard()

    if any(f is not None for f in (min_score, max_score, grade, generator_type, category)):
        filtered = report["templates"]
        if min_score is not None:
            filtered = [t for t in filtered if t["total"] >= min_score]
        if max_score is not None:
            filtered = [t for t in filtered if t["total"] <= max_score]
        if grade is not None:
            filtered = [t for t in filtered if t["grade"] == grade.upper()]
        if generator_type is not None:
            filtered = [t for t in filtered if t["generator_type"] == generator_type]
        if category is not None:
            filtered = [t for t in filtered if t["category"] == category]
        report = {**report, "templates": filtered, "filtered_count": len(filtered)}

    return report
