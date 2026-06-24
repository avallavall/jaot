"""
Seed the model_catalog with official JAOT models.

Reads YAML template files from ``app/data/templates/``, validates them with
Pydantic, and upserts into the ``model_catalog`` table.  Templates that are
no longer present in the YAML files get ``status='deprecated'`` in the DB
(never deleted).
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.data.templates import load_all_templates
from app.data.templates._schema import TemplateDefinition
from app.models import ModelCatalog
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


def seed_official_models(db: Session) -> int:
    """Upsert official models from YAML template files.

    * New templates are created with ``status='published'``.
    * Existing templates are updated in-place (upsert).
    * Templates that no longer appear in the YAML source get
      ``status='deprecated'``.

    Uses ``db.flush()`` (caller-commits pattern) so the function is composable
    inside a larger transaction such as the app lifespan.

    Returns the number of templates processed.
    """
    templates = load_all_templates()
    seen_ids: set[str] = set()
    count = 0

    for template in templates:
        catalog_id = f"official_{template.id}"
        seen_ids.add(catalog_id)

        existing = db.query(ModelCatalog).filter(ModelCatalog.id == catalog_id).first()

        merged_tags = template.tags + template.problem_type_tags

        if existing:
            existing.name = template.name
            existing.display_name = template.display_name
            existing.description = template.description
            existing.short_description = template.short_description
            existing.scenario_description = template.scenario_description
            existing.category = template.category
            existing.tags = merged_tags
            existing.generator_type = template.generator_type
            existing.input_schema = build_input_schema(template)
            existing.input_fields = [f.model_dump() for f in template.input_fields]
            existing.example_input = template.example_input
            existing.version = template.version
            existing.credits_per_execution = 1
            existing.is_featured = template.is_featured
            existing.status = "published"
            existing.updated_at = utcnow()
            logger.info("  Updated: %s", template.id)
        else:
            model = ModelCatalog(
                id=catalog_id,
                name=template.name,
                display_name=template.display_name,
                description=template.description,
                short_description=template.short_description,
                scenario_description=template.scenario_description,
                category=template.category,
                tags=merged_tags,
                generator_type=template.generator_type,
                input_schema=build_input_schema(template),
                input_fields=[f.model_dump() for f in template.input_fields],
                example_input=template.example_input,
                version=template.version,
                status="published",
                is_official=True,
                is_featured=template.is_featured,
                is_public=True,
                price_eur=0.0,
                credits_per_execution=1,
                published_at=utcnow(),
            )
            db.add(model)
            logger.info("  Created: %s", template.id)

        count += 1

    # Deprecate official models that are no longer in the YAML source
    stale = db.query(ModelCatalog).filter(
        ModelCatalog.is_official.is_(True),
        ModelCatalog.status != "deprecated",
    )
    if seen_ids:
        stale = stale.filter(ModelCatalog.id.notin_(seen_ids))

    for model in stale.all():
        model.status = "deprecated"
        model.updated_at = utcnow()
        logger.info("  Deprecated: %s", model.id)

    db.flush()
    return count


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
