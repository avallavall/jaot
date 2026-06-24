"""Template loader that auto-scans YAML files in the templates directory.

Drop a new ``*.yaml`` file in this directory and call ``load_all_templates()``
to pick it up automatically.
"""

import logging
from pathlib import Path

from app.data.templates._schema import TemplateDefinition, load_templates_from_yaml

logger = logging.getLogger(__name__)

__all__ = [
    "load_all_templates",
    "load_templates_from_yaml",
    "TemplateDefinition",
    "get_category_generator_map",
    "get_yaml_template",
]

_DEFAULT_DIR = Path(__file__).parent

# Module-level cache: loaded once on first call, reused thereafter.
_cached_templates: list[TemplateDefinition] | None = None
_cached_templates_by_id: dict[str, TemplateDefinition] | None = None


def load_all_templates(
    directory: Path | None = None,
) -> list[TemplateDefinition]:
    """Auto-scan ``*.yaml`` files and return a flat list of validated templates.

    Results are cached after the first call (for the default directory).
    Files that fail parsing or validation are skipped with a warning so that
    one broken file does not prevent the rest from loading.
    """
    global _cached_templates, _cached_templates_by_id  # noqa: PLW0603

    scan_dir = directory or _DEFAULT_DIR

    # Return cache if available (only for default directory)
    if directory is None and _cached_templates is not None:
        return _cached_templates

    templates: list[TemplateDefinition] = []

    yaml_files = sorted(scan_dir.glob("*.yaml"))
    if not yaml_files:
        logger.info("No YAML template files found in %s", scan_dir)
        if directory is None:
            _cached_templates = templates
            _cached_templates_by_id = {}
        return templates

    for yaml_file in yaml_files:
        try:
            content = yaml_file.read_text(encoding="utf-8")
            category_file = load_templates_from_yaml(content)
            templates.extend(category_file.templates)
            logger.info(
                "Loaded %d templates from %s",
                len(category_file.templates),
                yaml_file.name,
            )
        except Exception:
            logger.warning("Failed to load template file %s", yaml_file.name, exc_info=True)

    # Cache for default directory
    if directory is None:
        _cached_templates = templates
        _cached_templates_by_id = {t.id: t for t in templates}
        logger.info("Cached %d YAML templates", len(templates))

    return templates


def get_yaml_template(template_id: str) -> TemplateDefinition | None:
    """Look up a single YAML template by ID. Uses the cached index."""
    if _cached_templates_by_id is None:
        load_all_templates()
    return (_cached_templates_by_id or {}).get(template_id)


def get_category_generator_map(
    directory: Path | None = None,
) -> dict[str, list[str]]:
    """Build a mapping of category -> unique sorted generator_type values.

    Scans all YAML template files and groups generator types by their
    template category.  Useful for filtering which generators are relevant
    to a given problem category.

    Returns a dict like ``{"finance": ["budget_allocation", "generic", ...], ...}``.
    """
    templates = load_all_templates(directory)
    mapping: dict[str, set[str]] = {}
    for tmpl in templates:
        mapping.setdefault(tmpl.category, set()).add(tmpl.generator_type)
    return {cat: sorted(gens) for cat, gens in sorted(mapping.items())}
