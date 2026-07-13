"""Seed the official JAOT models from the YAML templates.

Reads YAML template files from ``app/data/templates/``, validates them with
Pydantic, and upserts them as the unified marketplace entity: a thin anchor
``ModelProject`` (owned by the system org ``org_jaot_official``) plus its
``ModelProjectListing`` facet carrying the generator + presentation. Officials
are generator-backed — the listing holds ``generator_type``/``input_schema``/
``input_fields``/``example_input`` and the generator is rendered at consume-time
(``/projects/from-marketplace/{id}``), so the anchor project needs no draft.

Templates that are no longer present in the YAML source get
``status='deprecated'`` on their listing (never deleted).
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.data.templates import load_all_templates
from app.data.templates._schema import TemplateDefinition
from app.models import ModelProject, ModelProjectListing, Organization
from app.shared.db.p15_backfill import SYSTEM_ORG_ID, SYSTEM_ORG_NAME
from app.shared.db.session import SessionLocal
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


def build_input_schema(template: TemplateDefinition) -> dict[str, Any]:
    """Build a JSON Schema ``dict`` from a TemplateDefinition's input_fields."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for field in template.input_fields:
        prop: dict[str, Any] = {"description": field.description}

        if field.type == "number":
            prop["type"] = "number"
            if field.minimum is not None:
                prop["minimum"] = field.minimum
            if field.maximum is not None:
                prop["maximum"] = field.maximum
        elif field.type == "integer":
            prop["type"] = "integer"
            if field.minimum is not None:
                prop["minimum"] = field.minimum
            if field.maximum is not None:
                prop["maximum"] = field.maximum
        elif field.type == "array":
            prop["type"] = "array"
            if field.items is not None:
                prop["items"] = field.items
        elif field.type == "object":
            prop["type"] = "object"
        elif field.type == "boolean":
            prop["type"] = "boolean"
        else:
            prop["type"] = "string"
            if field.enum is not None:
                prop["enum"] = field.enum

        properties[field.name] = prop

        if field.required:
            required.append(field.name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def ensure_official_org(db: Session) -> str:
    """Return the id of the officials-owning system org, creating it if absent.

    Idempotent (flush-only, caller-commits). Shares the id/name with the P1.5
    backfill so an existing backfilled DB and a fresh install converge on the
    same ``org_jaot_official`` row.
    """
    org = db.query(Organization).filter(Organization.id == SYSTEM_ORG_ID).first()
    if org is None:
        db.add(Organization(id=SYSTEM_ORG_ID, name=SYSTEM_ORG_NAME, is_public_profile=False))
        db.flush()
    return SYSTEM_ORG_ID


def _apply_listing_fields(
    listing: ModelProjectListing, template: TemplateDefinition, merged_tags: list[str]
) -> None:
    """Copy a template's presentation + generator facet onto a listing row."""
    listing.name = template.name
    listing.display_name = template.display_name
    listing.description = template.description
    listing.short_description = template.short_description
    listing.scenario_description = template.scenario_description
    listing.category = template.category
    listing.tags = merged_tags
    listing.generator_type = template.generator_type
    listing.input_schema = build_input_schema(template)
    listing.input_fields = [f.model_dump() for f in template.input_fields]
    listing.example_input = template.example_input
    listing.version = template.version
    listing.is_official = True
    listing.is_featured = template.is_featured
    listing.is_public = True
    listing.status = "published"


def seed_official_models(db: Session) -> int:
    """Upsert official models from YAML template files into the unified entity.

    * New templates create an anchor ``ModelProject`` (system org) + published
      ``ModelProjectListing``.
    * Existing ones are updated in-place (upsert, id ``official_{template.id}``).
    * Templates that no longer appear in the YAML source get ``status='deprecated'``
      on their listing.

    Uses ``db.flush()`` (caller-commits pattern) so the function is composable
    inside a larger transaction such as the app lifespan.

    Returns the number of templates processed.
    """
    org_id = ensure_official_org(db)
    templates = load_all_templates()
    seen_ids: set[str] = set()
    count = 0

    for template in templates:
        official_id = f"official_{template.id}"
        seen_ids.add(official_id)
        merged_tags = template.tags + template.problem_type_tags
        now = utcnow()

        # Anchor ModelProject (thin — the model content is the generator facet on
        # the listing, rendered at consume-time; no draft needed).
        project = db.query(ModelProject).filter(ModelProject.id == official_id).first()
        if project is None:
            project = ModelProject(
                id=official_id,
                organization_id=org_id,
                name=template.display_name,
                description=template.description,
                status="active",
                source_type="official",
            )
            db.add(project)
        else:
            project.organization_id = org_id
            project.name = template.display_name
            project.description = template.description
            project.status = "active"

        # Marketplace listing facet.
        listing = (
            db.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id == official_id)
            .first()
        )
        if listing is None:
            listing = ModelProjectListing(model_project_id=official_id, published_at=now)
            _apply_listing_fields(listing, template, merged_tags)
            db.add(listing)
        else:
            _apply_listing_fields(listing, template, merged_tags)
            if listing.published_at is None:
                listing.published_at = now

        logger.info("  Seeded official: %s", template.id)
        count += 1

    _deprecate_stale(db, seen_ids)

    db.flush()
    return count


def _deprecate_stale(db: Session, seen_ids: set[str]) -> None:
    """Deprecate official listings no longer in the YAML source."""
    stale_listings = db.query(ModelProjectListing).filter(
        ModelProjectListing.is_official.is_(True),
        ModelProjectListing.status != "deprecated",
    )
    if seen_ids:
        stale_listings = stale_listings.filter(
            ModelProjectListing.model_project_id.notin_(seen_ids)
        )
    for listing in stale_listings.all():
        listing.status = "deprecated"
        logger.info("  Deprecated: %s", listing.model_project_id)


def seed_models() -> None:
    """Wrapper that opens its own session and commits.

    Used by the CLI entry-point and standalone invocation.
    """
    logger.info("Seeding official models...")

    db = SessionLocal()
    try:
        count = seed_official_models(db)
        db.commit()
        logger.info("Seeded %d official models", count)
    except Exception as e:
        logger.error("Failed to seed models: %s", e)
        db.rollback()
        raise
    finally:
        db.close()


def seed_models_cli() -> None:
    """CLI entry-point with logging setup."""
    logging.basicConfig(level=logging.INFO)
    seed_models()


if __name__ == "__main__":
    seed_models_cli()
