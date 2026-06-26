"""Template Quality Scorecard — automated scoring for YAML templates.

Evaluates each template across 5 categories (20 pts each, 100 total):
  - Metadata completeness
  - Input schema quality
  - Example input quality
  - Generator quality
  - Documentation quality

Criteria based on docs/research/P2_TEMPLATE_AUDIT_RESEARCH.md §6.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from app.data.templates import TemplateDefinition, load_all_templates
from app.domains.solver.services.generators import GeneratorRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CategoryScore:
    """Score for a single category with itemized deductions."""

    name: str
    score: int
    max_score: int
    notes: tuple[str, ...] = ()

    @property
    def percentage(self) -> float:
        return (self.score / self.max_score * 100) if self.max_score else 0.0


@dataclass(frozen=True)
class TemplateScore:
    """Complete scorecard for one template."""

    template_id: str
    template_name: str
    category: str
    generator_type: str
    categories: tuple[CategoryScore, ...] = ()

    @property
    def total(self) -> int:
        return sum(c.score for c in self.categories)

    @property
    def max_total(self) -> int:
        return sum(c.max_score for c in self.categories)

    @property
    def grade(self) -> str:
        pct = (self.total / self.max_total * 100) if self.max_total else 0
        if pct >= 90:
            return "A"
        if pct >= 80:
            return "B"
        if pct >= 70:
            return "C"
        if pct >= 60:
            return "D"
        return "F"

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "template_name": self.template_name,
            "category": self.category,
            "generator_type": self.generator_type,
            "total": self.total,
            "max_total": self.max_total,
            "grade": self.grade,
            "categories": [
                {
                    "name": c.name,
                    "score": c.score,
                    "max_score": c.max_score,
                    "notes": list(c.notes),
                }
                for c in self.categories
            ],
        }


def _score_metadata(t: TemplateDefinition) -> CategoryScore:
    """Metadata (20 pts): display_name, short_description, description,
    scenario_description, tags+problem_type_tags, estimated_vars/constraints."""
    pts = 0
    notes: list[str] = []

    # display_name present and descriptive (4 pts)
    if t.display_name and len(t.display_name) > 3:
        pts += 4
    else:
        notes.append("display_name missing or too short")

    # short_description present (4 pts)
    if t.short_description and len(t.short_description) >= 10:
        pts += 4
    else:
        notes.append("short_description missing or too short")

    # description present and informative (4 pts)
    if t.description and len(t.description) >= 30:
        pts += 4
    elif t.description:
        pts += 2
        notes.append("description too brief")
    else:
        notes.append("description missing")

    # scenario_description present (4 pts)
    if t.scenario_description and len(t.scenario_description) >= 20:
        pts += 4
    else:
        notes.append("scenario_description missing or too short")

    # tags + problem_type_tags complete (2 pts)
    if t.tags and t.problem_type_tags:
        pts += 2
    elif t.tags or t.problem_type_tags:
        pts += 1
        notes.append("tags or problem_type_tags missing")
    else:
        notes.append("both tags and problem_type_tags missing")

    # estimated_variables/constraints (2 pts)
    if t.estimated_variables is not None and t.estimated_constraints is not None:
        pts += 2
    elif t.estimated_variables is not None or t.estimated_constraints is not None:
        pts += 1
        notes.append("only one of estimated_variables/constraints present")
    else:
        notes.append("estimated_variables and estimated_constraints missing")

    return CategoryScore(name="metadata", score=pts, max_score=20, notes=tuple(notes))


def _score_input_schema(t: TemplateDefinition) -> CategoryScore:
    """Input Schema (20 pts): field labels, types, required/optional, defaults, validation."""
    pts = 0
    notes: list[str] = []
    fields = t.input_fields

    if not fields:
        return CategoryScore(
            name="input_schema", score=0, max_score=20, notes=("no input_fields defined",)
        )

    # All fields have label + description (5 pts)
    fields_with_label = sum(1 for f in fields if f.label)
    fields_with_desc = sum(1 for f in fields if f.description)
    label_ratio = fields_with_label / len(fields)
    desc_ratio = fields_with_desc / len(fields)
    label_pts = round(2.5 * label_ratio)
    desc_pts = round(2.5 * desc_ratio)
    pts += label_pts + desc_pts
    if label_ratio < 1:
        notes.append(f"{len(fields) - fields_with_label} fields missing label")
    if desc_ratio < 1:
        notes.append(f"{len(fields) - fields_with_desc} fields missing description")

    # Types correct (5 pts) — all fields have a valid type
    valid_types = {"number", "integer", "string", "boolean", "array", "object"}
    fields_valid_type = sum(1 for f in fields if f.type in valid_types)
    pts += round(5 * fields_valid_type / len(fields))
    if fields_valid_type < len(fields):
        notes.append("some fields have invalid types")

    # Required/optional correct (3 pts) — at least some fields marked required
    has_required = any(f.required for f in fields)
    has_optional = any(not f.required for f in fields)
    if has_required:
        pts += 2
    else:
        notes.append("no fields marked as required")
    if has_optional or len(fields) <= 2:
        pts += 1
    else:
        notes.append("no optional fields defined")

    # Defaults present where optional (3 pts)
    optional_fields = [f for f in fields if not f.required]
    if not optional_fields:
        pts += 3  # no optional fields = no defaults needed
    else:
        with_defaults = sum(1 for f in optional_fields if f.default is not None)
        pts += round(3 * with_defaults / len(optional_fields))
        missing = len(optional_fields) - with_defaults
        if missing:
            notes.append(f"{missing} optional fields missing defaults")

    # Validation (min/max/enum) (4 pts)
    fields_with_validation = sum(
        1
        for f in fields
        if f.minimum is not None or f.maximum is not None or f.enum is not None or f.items
    )
    if fields_with_validation > 0:
        ratio = min(1.0, fields_with_validation / max(1, len(fields) - 1))
        pts += round(4 * ratio)
    else:
        notes.append("no validation constraints (min/max/enum) on any field")

    return CategoryScore(name="input_schema", score=min(pts, 20), max_score=20, notes=tuple(notes))


def _score_example_input(t: TemplateDefinition) -> CategoryScore:
    """Example Input (20 pts): present, complete, realistic, solvable."""
    pts = 0
    notes: list[str] = []
    example = t.example_input

    # Present (5 pts)
    if not example:
        return CategoryScore(
            name="example_input", score=0, max_score=20, notes=("no example_input defined",)
        )
    pts += 5

    # Complete — all required input_fields present in example (5 pts)
    required_names = {f.name for f in t.input_fields if f.required}
    example_keys = set(example.keys())
    missing = required_names - example_keys
    if not missing:
        pts += 5
    else:
        covered = len(required_names) - len(missing)
        pts += round(5 * covered / max(1, len(required_names)))
        notes.append(f"example missing required fields: {sorted(missing)}")

    # Realistic data (5 pts) — heuristic: non-trivial values, multiple items in arrays
    realism_score = _estimate_realism(example)
    pts += realism_score
    if realism_score < 5:
        notes.append("example data could be more realistic")

    # Solvable (5 pts) — we can't solve without the full stack, so score by structure
    # Check that numeric values are positive, arrays non-empty, no obvious contradictions
    structural_pts = _estimate_solvability(example)
    pts += structural_pts
    if structural_pts < 5:
        notes.append("example may have solvability issues")

    return CategoryScore(name="example_input", score=min(pts, 20), max_score=20, notes=tuple(notes))


def _estimate_realism(data: dict[str, Any]) -> int:
    """Heuristic: score 0-5 for how realistic example data looks."""
    indicators: float = 0
    total_checks = 0

    for v in data.values():
        total_checks += 1
        if isinstance(v, list):
            # Arrays with 3+ items score higher
            if len(v) >= 3:
                indicators += 1
            elif len(v) >= 1:
                indicators += 0.5
        elif isinstance(v, dict):
            # Nested dicts indicate structured data
            indicators += 0.5 + (0.5 if len(v) >= 2 else 0)
        elif isinstance(v, (int, float)):
            # Non-zero, non-trivial numbers
            if v not in (0, 1, -1):
                indicators += 1
        elif isinstance(v, str) and len(v) > 2:
            indicators += 0.5

    if total_checks == 0:
        return 2
    ratio = indicators / total_checks
    return min(5, round(5 * ratio))


def _estimate_solvability(data: dict[str, Any]) -> int:
    """Heuristic: score 0-5 for structural soundness of example."""
    issues = 0

    for v in data.values():
        if isinstance(v, list) and len(v) == 0 or isinstance(v, dict) and len(v) == 0:
            issues += 1

    if issues == 0:
        return 5
    if issues == 1:
        return 3
    return 1


def _score_generator(t: TemplateDefinition) -> CategoryScore:
    """Generator Quality (20 pts): specialized, validates, handles optional, descriptive names."""
    pts = 0
    notes: list[str] = []

    # Uses specialized generator, not generic (5 pts)
    is_generic = t.generator_type == "generic"
    if not is_generic:
        pts += 5
    else:
        notes.append("uses generic generator instead of specialized")

    # Generator registered in registry (5 pts) + validates input (5 pts)
    generator_cls = GeneratorRegistry._generators.get(t.generator_type)
    if generator_cls is not None:
        pts += 5
        has_validate = hasattr(generator_cls, "validate_input") or hasattr(
            generator_cls, "_validate"
        )
        if has_validate:
            pts += 5
        else:
            pts += 3
            notes.append("generator lacks explicit validate_input method")
    else:
        logger.warning("Scorecard: generator '%s' not found in registry", t.generator_type)
        notes.append(f"generator '{t.generator_type}' not found in registry")

    # Descriptive variable names (5 pts) — partial, check generator_params for hints
    if not is_generic:
        pts += 5  # specialized generators produce domain-specific names
    else:
        pts += 2
        notes.append("generic generator produces generic variable names")

    return CategoryScore(name="generator", score=min(pts, 20), max_score=20, notes=tuple(notes))


def _score_documentation(t: TemplateDefinition) -> CategoryScore:
    """Documentation (20 pts): use case, math formulation, assumptions, limitations."""
    pts = 0
    notes: list[str] = []
    desc = (t.description or "") + " " + (t.scenario_description or "")
    desc_lower = desc.lower()

    # Description explains use case (5 pts)
    use_case_keywords = [
        "useful for",
        "used in",
        "applies to",
        "helps",
        "designed for",
        "ideal for",
        "suitable for",
        "common in",
        "planning",
        "logistics",
        "scheduling",
        "manufacturing",
        "optimize",
    ]
    use_case_hits = sum(1 for kw in use_case_keywords if kw in desc_lower)
    if use_case_hits >= 2:
        pts += 5
    elif use_case_hits >= 1:
        pts += 3
    elif len(desc) > 50:
        pts += 2
    else:
        notes.append("description doesn't explain use case")

    # Math formulation implied (5 pts)
    math_keywords = [
        "minimize",
        "maximize",
        "subject to",
        "constraint",
        "objective",
        "linear",
        "integer",
        "binary",
        "variable",
        "optimal",
        "feasible",
        "bound",
        "solver",
    ]
    math_hits = sum(1 for kw in math_keywords if kw in desc_lower)
    if math_hits >= 3:
        pts += 5
    elif math_hits >= 1:
        pts += 3
    else:
        notes.append("no math formulation implied in description")

    # Assumptions stated (5 pts) — scenario_description usually carries this
    if t.scenario_description and len(t.scenario_description) >= 50:
        pts += 5
    elif t.scenario_description:
        pts += 3
        notes.append("scenario_description too brief for assumptions")
    else:
        notes.append("no scenario_description (assumptions not stated)")

    # Limitations/edge cases noted (5 pts)
    limitation_keywords = [
        "limitation",
        "edge case",
        "assumes",
        "does not",
        "cannot",
        "only",
        "at most",
        "at least",
        "note that",
        "caveat",
    ]
    limit_hits = sum(1 for kw in limitation_keywords if kw in desc_lower)
    if limit_hits >= 2:
        pts += 5
    elif limit_hits >= 1:
        pts += 3
    elif len(desc) > 200:
        pts += 2  # long descriptions implicitly scope the problem
    else:
        notes.append("no limitations or edge cases documented")

    return CategoryScore(name="documentation", score=min(pts, 20), max_score=20, notes=tuple(notes))


def score_template(t: TemplateDefinition) -> TemplateScore:
    """Score a single template across all 5 categories."""
    categories = (
        _score_metadata(t),
        _score_input_schema(t),
        _score_example_input(t),
        _score_generator(t),
        _score_documentation(t),
    )
    return TemplateScore(
        template_id=t.id,
        template_name=t.display_name,
        category=t.category,
        generator_type=t.generator_type,
        categories=categories,
    )


_cached_report: dict[str, Any] | None = None


def run_scorecard() -> dict[str, Any]:
    """Run quality scorecard on all YAML templates. Returns cached report.

    Results are cached at module level since templates only change on deploy.
    """
    global _cached_report  # noqa: PLW0603
    if _cached_report is not None:
        return _cached_report

    templates = load_all_templates()
    scores = [score_template(t) for t in templates]

    # Single pass for aggregation
    total_sum = 0
    grade_counter: Counter[str] = Counter()
    by_gen: dict[str, list[int]] = defaultdict(list)
    for s in scores:
        total_sum += s.total
        grade_counter[s.grade] += 1
        by_gen[s.generator_type].append(s.total)

    avg = total_sum / len(scores) if scores else 0.0
    gen_avg = {g: sum(v) / len(v) for g, v in by_gen.items()}
    scores_sorted = sorted(scores, key=lambda s: s.total, reverse=True)

    _cached_report = {
        "total_templates": len(scores),
        "average_score": round(avg, 1),
        "grade_distribution": dict(grade_counter),
        "by_generator_type": {g: round(v, 1) for g, v in sorted(gen_avg.items())},
        "top_5": [f"{s.template_id} ({s.total})" for s in scores_sorted[:5]],
        "bottom_5": [f"{s.template_id} ({s.total})" for s in scores_sorted[-5:]],
        "templates": [s.to_dict() for s in scores_sorted],
    }
    return _cached_report
