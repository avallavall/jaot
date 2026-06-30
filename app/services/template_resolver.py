"""Resolve a template id to an engine-ready template dict.

A "template id" can name either a YAML template (``app/data/templates/*.yaml``) or
a *published* marketplace catalog row (``ModelCatalog``). This module is the SINGLE
resolution path, shared by:

* the template-solve routes (``app/domains/solver/routes/templates.py``), and
* the ModelProject "create from template / marketplace" endpoints (P2,
  ``app/api/v2/projects.py``),

so the two never drift. The actual materialization (template dict → Optimization
problem) stays in ``TemplateEngine.render``; this module only turns an id into the
dict the engine expects.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.data.templates import TemplateDefinition, get_yaml_template
from app.models import ModelCatalog

# Origin tags — also reused verbatim as the ModelProject ``source_type`` provenance.
ORIGIN_TEMPLATE = "template"
ORIGIN_MARKETPLACE = "marketplace"


def yaml_template_to_dict(tmpl: TemplateDefinition) -> dict[str, Any]:
    """Convert a YAML TemplateDefinition to a template dict for the engine."""
    return {**tmpl.model_dump(), "generator": tmpl.generator_type}


def catalog_model_to_dict(model: ModelCatalog) -> dict[str, Any]:
    """Convert a published ModelCatalog row to a template dict for the engine."""
    return {
        "id": model.id,
        "name": model.name,
        "display_name": model.display_name,
        "description": model.description,
        "scenario_description": model.scenario_description,
        "category": model.category,
        "tags": model.tags or [],
        "generator": model.generator_type,
        "generator_type": model.generator_type,
        "input_schema": model.input_schema,
        "input_fields": model.input_fields,
        "example_input": model.example_input,
    }


def resolve_template(
    template_id: str,
    db: Session,
) -> tuple[dict[str, Any] | None, ModelCatalog | None]:
    """Return ``(yaml_template_dict, None)`` or ``(None, catalog_model)``.

    Resolution order: YAML templates first, then a *published* DB catalog row
    (matched on either the bare id or the ``official_`` prefixed id). Both are
    ``None`` when ``template_id`` matches nothing.
    """
    yaml_tmpl = get_yaml_template(template_id)
    if yaml_tmpl:
        return yaml_template_to_dict(yaml_tmpl), None

    model = (
        db.query(ModelCatalog)
        .filter(
            ModelCatalog.id.in_([template_id, f"official_{template_id}"]),
            ModelCatalog.status == "published",
        )
        .first()
    )
    if model:
        return None, model

    return None, None


def resolve_template_dict(
    template_id: str,
    db: Session,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a template id to a single engine-ready dict plus its origin.

    Returns ``(template_dict, origin)`` where ``origin`` is :data:`ORIGIN_TEMPLATE`
    (a YAML template) or :data:`ORIGIN_MARKETPLACE` (a published catalog model), or
    ``(None, None)`` when the id matches nothing. The origin doubles as the
    ModelProject ``source_type`` for provenance.
    """
    yaml_dict, model = resolve_template(template_id, db)
    if yaml_dict is not None:
        return yaml_dict, ORIGIN_TEMPLATE
    if model is not None:
        return catalog_model_to_dict(model), ORIGIN_MARKETPLACE
    return None, None
