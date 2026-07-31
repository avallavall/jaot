"""Resolve a template / marketplace id to an engine-ready template dict.

A "template id" can name either a YAML template (``app/data/templates/*.yaml``) or a
*published* marketplace listing (``ModelProjectListing`` — P1.5 fusion; the model
content lives on the project/version, the listing is its marketplace facet). This
module is the SINGLE resolution path, shared by:

* the template-solve routes (``app/domains/solver/routes/templates.py``), and
* the ModelProject "create from template / marketplace" endpoints (``app/api/v2/projects.py``),

so the two never drift. The actual materialization (template dict → OptimizationProblem)
stays in ``TemplateEngine.render``; this module only turns an id into the dict the engine
expects. A **generator-backed** listing (officials) carries a generator facet and renders
through the engine; a **static** published project has no generator — it is consumed by
copying its pinned committed version's ``model_json`` (see ``resolve_static_listing``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.data.templates import TemplateDefinition, get_yaml_template
from app.models.model_project import ModelProjectListing, ModelProjectVersion
from app.services.marketplace_fusion import MARKETPLACE_VISIBLE

# Origin tags — also reused verbatim as the ModelProject ``source_type`` provenance.
ORIGIN_TEMPLATE = "template"
ORIGIN_MARKETPLACE = "marketplace"


def yaml_template_to_dict(tmpl: TemplateDefinition) -> dict[str, Any]:
    """Convert a YAML TemplateDefinition to a template dict for the engine."""
    return {**tmpl.model_dump(), "generator": tmpl.generator_type}


def listing_to_template_dict(listing: ModelProjectListing) -> dict[str, Any]:
    """Convert a generator-backed marketplace listing to a template dict for the engine."""
    return {
        "id": listing.model_project_id,
        "name": listing.name,
        "display_name": listing.display_name,
        "description": listing.description,
        "scenario_description": listing.scenario_description,
        "category": listing.category,
        "tags": listing.tags or [],
        "generator": listing.generator_type,
        "generator_type": listing.generator_type,
        "input_schema": listing.input_schema,
        "input_fields": listing.input_fields,
        "example_input": listing.example_input,
    }


def _published_listing(db: Session, model_id: str):  # noqa: ANN202
    """A published, public listing matched on the bare or ``official_``-prefixed id."""
    return (
        db.query(ModelProjectListing)
        .filter(
            ModelProjectListing.model_project_id.in_([model_id, f"official_{model_id}"]),
            *MARKETPLACE_VISIBLE,
        )
        .first()
    )


def resolve_template(
    template_id: str,
    db: Session,
) -> tuple[dict[str, Any] | None, ModelProjectListing | None]:
    """Return ``(yaml_template_dict, None)`` or ``(None, generator_listing)``.

    Resolution order: YAML templates first, then a *published and public*
    **generator-backed** listing (a listing whose generator facet is set). Both are
    ``None`` when ``template_id`` matches nothing renderable — a static listing is NOT
    returned here (it has no generator; use :func:`resolve_static_listing`).
    """
    yaml_tmpl = get_yaml_template(template_id)
    if yaml_tmpl:
        return yaml_template_to_dict(yaml_tmpl), None

    listing = _published_listing(db, template_id)
    if listing is not None and listing.generator_type:
        return None, listing

    return None, None


def resolve_template_dict(
    template_id: str,
    db: Session,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a template id to a single engine-ready dict plus its origin.

    Returns ``(template_dict, origin)`` where ``origin`` is :data:`ORIGIN_TEMPLATE`
    (a YAML template) or :data:`ORIGIN_MARKETPLACE` (a generator-backed listing), or
    ``(None, None)`` when nothing renderable matches. The origin doubles as the
    ModelProject ``source_type`` for provenance.
    """
    yaml_dict, listing = resolve_template(template_id, db)
    if yaml_dict is not None:
        return yaml_dict, ORIGIN_TEMPLATE
    if listing is not None:
        return listing_to_template_dict(listing), ORIGIN_MARKETPLACE
    return None, None


def resolve_static_listing(
    template_id: str,
    db: Session,
) -> tuple[ModelProjectListing, ModelProjectVersion] | None:
    """Resolve a published *static* listing (no generator) to its pinned version.

    A static listing is a plain published project — its model is the ``model_json`` of
    the committed version pinned at publish time. Returns ``(listing, version)`` or
    ``None`` (not published/public, generator-backed, or the pinned version is gone).
    """
    listing = _published_listing(db, template_id)
    if listing is None or listing.generator_type or not listing.pinned_version_id:
        return None
    version = (
        db.query(ModelProjectVersion)
        .filter(ModelProjectVersion.id == listing.pinned_version_id)
        .first()
    )
    if version is None:
        return None
    return listing, version
