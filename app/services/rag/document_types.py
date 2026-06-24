"""Document extractors for the RAG knowledge corpus.

Each extractor produces a list of dicts with keys:
    id:      Deterministic ID for idempotent upserts
    text:    Synthesized text to embed (with contextual prefix)
    payload: Qdrant metadata payload

Document types:
    1. Template summaries   — from YAML template definitions
    2. Generator patterns   — from generator Python source files
    3. Constraint patterns  — from app/data/rag/constraint_patterns.yaml
    4. Linearization techs  — from app/data/rag/linearization.yaml
    5. Parser capabilities  — from app/data/rag/parser_capabilities.yaml
    6. Industry vocabulary   — synthesized from template category files
"""

from __future__ import annotations

import ast
import logging
from enum import Enum
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


# Document type enum — prevents silent typo bugs in payload/prefix logic
class DocType(str, Enum):
    TEMPLATE = "template"
    GENERATOR = "generator"
    CONSTRAINT_PATTERN = "constraint_pattern"
    LINEARIZATION = "linearization"
    PARSER_CAPABILITY = "parser_capability"
    INDUSTRY_VOCABULARY = "industry_vocabulary"


# Problem archetypes — maps generator_type to archetype description
_PROBLEM_ARCHETYPES: dict[str, str] = {
    "knapsack": "0-1 knapsack (combinatorial, NP-hard)",
    "bin_packing": "bin packing (combinatorial, NP-hard)",
    "assignment": "assignment problem (polynomial via Hungarian, NP-hard for MIP extensions)",
    "scheduling": "scheduling / timetabling (combinatorial, NP-hard)",
    "routing": "vehicle routing CVRP (combinatorial, NP-hard)",
    "network_flow": "network flow (polynomial for LP, NP-hard for integer)",
    "production": "production planning / lot sizing (MIP)",
    "facility_location": "facility location (combinatorial, NP-hard)",
    "portfolio": "portfolio optimization (QP/MIP)",
    "blending": "blending / mixing (LP)",
    "lot_sizing": "lot sizing with setup costs (MIP)",
    "cutting_stock": "cutting stock / 1D cutting (MIP)",
    "covering": "set covering / minimum cover (MIP)",
    "set_cover": "set cover (combinatorial, NP-hard)",
    "strip_packing": "2D strip packing (combinatorial, NP-hard)",
    "spanning_tree": "minimum spanning tree (polynomial, MIP formulation)",
    "mdpdp": "multi-depot pickup-delivery with time windows (NP-hard)",
    "fleet_sizing": "fleet sizing and allocation (MIP)",
    "cash_flow": "cash flow optimization (LP/MIP)",
    "energy_storage": "energy storage dispatch (MIP)",
    "crop_rotation": "crop rotation planning (MIP)",
    "irrigation": "irrigation scheduling (LP/MIP)",
    "markdown_pricing": "markdown pricing / clearance (MIP)",
    "procurement": "procurement / sourcing (MIP)",
    "quality_control": "quality control / inspection (MIP)",
    "renewable": "renewable energy planning (MIP)",
    "generic": "generic optimization (user-defined formulation)",
}

_DISAMBIGUATION: dict[str, str] = {
    "knapsack": "Not to be confused with: bin packing (multiple bins), set cover (coverage objective).",
    "bin_packing": "Not to be confused with: knapsack (single capacity, value objective), cutting stock (1D rolls).",
    "assignment": "Not to be confused with: set partitioning (rows can overlap), scheduling (time dimension).",
    "set_cover": "Not to be confused with: covering (minimum cost coverage), assignment (one-to-one).",
    "routing": "Not to be confused with: TSP (single vehicle, no capacity), network flow (no vehicle concept).",
    "scheduling": "Not to be confused with: assignment (no time dimension), lot sizing (production focus).",
    "facility_location": "Not to be confused with: set cover (no distance/cost), assignment (no facility opening).",
}


def _data_dir() -> Path:
    """Return the app/data directory."""
    return Path(__file__).resolve().parent.parent.parent / "data"


def _load_yaml(path: Path, label: str) -> dict[str, Any] | None:
    """Load and parse a YAML file, returning None on failure."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("File not found: %s (%s)", path, label)
        return None
    except yaml.YAMLError:
        logger.warning("Malformed YAML: %s (%s)", path, label, exc_info=True)
        return None
    except Exception:
        logger.warning("Failed to read %s (%s)", path, label, exc_info=True)
        return None


_CONTEXT_PREFIXES: dict[DocType, str] = {
    DocType.TEMPLATE: "This is a JAOT optimization template for {context}. ",
    DocType.GENERATOR: "This is a JAOT code generator for {context} optimization problems. ",
    DocType.CONSTRAINT_PATTERN: (
        "This is a reusable constraint pattern called {context} "
        "for mathematical optimization formulations. "
    ),
    DocType.LINEARIZATION: (
        "This is a linearization technique called {context} "
        "for reformulating nonlinear expressions into linear constraints. "
    ),
    DocType.PARSER_CAPABILITY: "This describes JAOT expression parser capabilities: {context}. ",
    DocType.INDUSTRY_VOCABULARY: (
        "This maps industry-specific terminology from {context} "
        "to optimization problem types and generators. "
    ),
}


def _add_contextual_prefix(text: str, doc_type: DocType, context: str) -> str:
    """Prepend a contextual sentence for better embedding retrieval."""
    template = _CONTEXT_PREFIXES[doc_type]
    return template.format(context=context) + text


def _load_all_template_files(
    templates_dir: Path | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Parse all template YAML files once. Returns (filename, data) pairs."""
    if templates_dir is None:
        templates_dir = _data_dir() / "templates"

    results: list[tuple[str, dict[str, Any]]] = []
    for yaml_file in sorted(templates_dir.glob("*.yaml")):
        data = _load_yaml(yaml_file, f"template:{yaml_file.name}")
        if data is not None:
            results.append((yaml_file.name, data))
    return results


def _extract_templates_from_parsed(
    parsed_files: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Extract template documents from pre-parsed YAML data."""
    documents: list[dict[str, Any]] = []

    for filename, data in parsed_files:
        category = data.get("category", "general")
        category_display = data.get("category_display_name", category)

        for template in data.get("templates", []):
            display_name = template.get("display_name", template.get("name", ""))
            doc_id = f"tmpl_{template['id']}_{category}"
            text = _synthesize_template_text(template, category_display)
            text = _add_contextual_prefix(
                text,
                DocType.TEMPLATE,
                f"{category_display} problems involving {display_name}",
            )

            documents.append(
                {
                    "id": doc_id,
                    "text": text,
                    "payload": {
                        "doc_type": DocType.TEMPLATE.value,
                        "template_id": template["id"],
                        "category": category,
                        "generator_type": template.get("generator_type", "generic"),
                        "problem_type_tags": template.get("problem_type_tags", []),
                        "tags": template.get("tags", []),
                        "display_name": display_name,
                        "is_featured": template.get("is_featured", False),
                        "estimated_variables": template.get("estimated_variables", 0),
                        "estimated_constraints": template.get("estimated_constraints", 0),
                        "source_file": filename,
                    },
                }
            )

    logger.info("Extracted %d template documents", len(documents))
    return documents


def extract_template_documents(
    templates_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract indexable documents from YAML template files."""
    return _extract_templates_from_parsed(_load_all_template_files(templates_dir))


def _synthesize_template_text(template: dict[str, Any], category_display: str) -> str:
    """Synthesize searchable text from a template definition."""
    parts: list[str] = [
        f"Template: {template.get('display_name', template.get('name', ''))}",
        f"Category: {category_display}",
    ]

    gen_type = template.get("generator_type", "generic")
    archetype = _PROBLEM_ARCHETYPES.get(gen_type)
    if archetype:
        parts.append(f"Archetype: {archetype}")

    if template.get("problem_type_tags"):
        parts.append(f"Problem Type: {', '.join(template['problem_type_tags'])}")

    if template.get("short_description"):
        parts.append(f"Summary: {template['short_description']}")

    if template.get("description"):
        parts.append(f"Description: {template['description']}")

    if template.get("scenario_description"):
        parts.append(f"Example Scenario: {template['scenario_description']}")

    if template.get("tags"):
        parts.append(f"Keywords: {', '.join(template['tags'])}")

    parts.append(f"Generator: {gen_type}")

    disambiguation = _DISAMBIGUATION.get(gen_type)
    if disambiguation:
        parts.append(disambiguation)

    return "\n".join(parts)


def extract_generator_documents(
    generators_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract indexable documents from generator Python source files."""
    if generators_dir is None:
        generators_dir = (
            Path(__file__).resolve().parent.parent.parent
            / "domains"
            / "solver"
            / "services"
            / "generators"
        )

    documents: list[dict[str, Any]] = []

    for py_file in sorted(generators_dir.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name == "base.py":
            continue

        generator_type = py_file.stem
        try:
            source = py_file.read_text(encoding="utf-8")
        except Exception:
            logger.warning("Failed to read %s, skipping", py_file.name)
            continue

        text = _synthesize_generator_text(generator_type, source)
        text = _add_contextual_prefix(text, DocType.GENERATOR, generator_type)

        documents.append(
            {
                "id": f"gen_{generator_type}",
                "text": text,
                "payload": {
                    "doc_type": DocType.GENERATOR.value,
                    "generator_type": generator_type,
                    "source_file": f"generators/{py_file.name}",
                },
            }
        )

    logger.info("Extracted %d generator documents", len(documents))
    return documents


def _synthesize_generator_text(generator_type: str, source: str) -> str:
    """Synthesize searchable text from generator source code."""
    parts: list[str] = [f"Generator: {generator_type}"]

    archetype = _PROBLEM_ARCHETYPES.get(generator_type)
    if archetype:
        parts.append(f"Archetype: {archetype}")

    try:
        tree = ast.parse(source)

        module_doc = ast.get_docstring(tree)
        if module_doc:
            parts.append(f"Description: {module_doc}")

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_doc = ast.get_docstring(node)
                if class_doc:
                    parts.append(f"Class {node.name}: {class_doc}")
    except SyntaxError:
        logger.warning("Failed to parse AST for generator %s", generator_type)

    return "\n".join(parts)


def extract_constraint_patterns(
    patterns_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract constraint pattern documents from YAML."""
    if patterns_file is None:
        patterns_file = _data_dir() / "rag" / "constraint_patterns.yaml"

    data = _load_yaml(patterns_file, "constraint_patterns")
    if data is None:
        return []

    documents: list[dict[str, Any]] = []

    for pattern in data.get("patterns", []):
        text = (
            f"Constraint Pattern: {pattern['name']}\n"
            f"Canonical Form: {pattern['form']}\n"
            f"Description: {pattern['description']}\n"
            f"Used in: {', '.join(pattern.get('used_in', []))}\n"
            f"Variables involved: {', '.join(pattern.get('variables', []))}\n"
            f"Example: {pattern.get('example', '')}"
        )
        if pattern.get("pitfalls"):
            text += f"\nPitfalls: {pattern['pitfalls']}"

        text = _add_contextual_prefix(text, DocType.CONSTRAINT_PATTERN, pattern["name"])

        documents.append(
            {
                "id": f"cstr_{pattern['id']}",
                "text": text,
                "payload": {
                    "doc_type": DocType.CONSTRAINT_PATTERN.value,
                    "pattern_name": pattern["name"],
                    "pattern_id": pattern["id"],
                    "used_in": pattern.get("used_in", []),
                },
            }
        )

    logger.info("Extracted %d constraint pattern documents", len(documents))
    return documents


def extract_linearization_techniques(
    techniques_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract linearization technique documents from YAML."""
    if techniques_file is None:
        techniques_file = _data_dir() / "rag" / "linearization.yaml"

    data = _load_yaml(techniques_file, "linearization")
    if data is None:
        return []

    documents: list[dict[str, Any]] = []

    for tech in data.get("techniques", []):
        text = (
            f"Linearization Technique: {tech['name']}\n"
            f"Original Form: {tech['form']}\n"
            f"Reformulation:\n{tech['reformulation']}\n"
            f"Description: {tech['description']}\n"
            f"When to use: {tech['when_to_use']}"
        )
        if tech.get("industry_examples"):
            text += "\nExamples:\n" + "\n".join(f"  - {ex}" for ex in tech["industry_examples"])
        if tech.get("pitfalls"):
            text += f"\nPitfalls: {tech['pitfalls']}"

        text = _add_contextual_prefix(text, DocType.LINEARIZATION, tech["name"])

        documents.append(
            {
                "id": f"lin_{tech['id']}",
                "text": text,
                "payload": {
                    "doc_type": DocType.LINEARIZATION.value,
                    "technique_name": tech["name"],
                    "technique_id": tech["id"],
                },
            }
        )

    logger.info("Extracted %d linearization documents", len(documents))
    return documents


def extract_parser_capabilities(
    capabilities_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract parser capability documents from YAML."""
    if capabilities_file is None:
        capabilities_file = _data_dir() / "rag" / "parser_capabilities.yaml"

    data = _load_yaml(capabilities_file, "parser_capabilities")
    if data is None:
        return []

    documents: list[dict[str, Any]] = []

    for doc in data.get("documents", []):
        text = f"{doc['title']}\n{doc['text']}"
        text = _add_contextual_prefix(text, DocType.PARSER_CAPABILITY, doc["title"])

        documents.append(
            {
                "id": f"parser_{doc['id']}",
                "text": text,
                "payload": {
                    "doc_type": DocType.PARSER_CAPABILITY.value,
                    "title": doc["title"],
                },
            }
        )

    logger.info("Extracted %d parser capability documents", len(documents))
    return documents


def _extract_vocabulary_from_parsed(
    parsed_files: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Extract vocabulary documents from pre-parsed template YAML data."""
    documents: list[dict[str, Any]] = []

    for _filename, data in parsed_files:
        category = data.get("category", "general")
        category_display = data.get("category_display_name", category)
        templates = data.get("templates", [])

        if not templates:
            continue

        term_mappings: list[str] = []
        generator_types: set[str] = set()
        all_tags: set[str] = set()

        for tmpl in templates:
            gen_type = tmpl.get("generator_type", "generic")
            generator_types.add(gen_type)
            display = tmpl.get("display_name", tmpl.get("name", ""))
            term_mappings.append(f'"{display}" -> {gen_type} generator')
            for tag in tmpl.get("tags", []):
                all_tags.add(tag)

        text = (
            f"Industry: {category_display}\n"
            f"Category: {category}\n"
            f"Optimization terms:\n"
            + "\n".join(f"  - {m}" for m in term_mappings)
            + f"\nGenerator types used: {', '.join(sorted(generator_types))}"
            + f"\nKeywords: {', '.join(sorted(all_tags))}"
        )
        text = _add_contextual_prefix(text, DocType.INDUSTRY_VOCABULARY, category_display)

        documents.append(
            {
                "id": f"vocab_{category}",
                "text": text,
                "payload": {
                    "doc_type": DocType.INDUSTRY_VOCABULARY.value,
                    "category": category,
                    "category_display": category_display,
                    "generator_types": sorted(generator_types),
                    "tags": sorted(all_tags),
                },
            }
        )

    logger.info("Extracted %d industry vocabulary documents", len(documents))
    return documents


def extract_industry_vocabulary(
    templates_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Synthesize industry vocabulary documents from template categories."""
    return _extract_vocabulary_from_parsed(_load_all_template_files(templates_dir))


def extract_all_documents(
    templates_dir: Path | None = None,
    generators_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Extract all document types for the RAG knowledge base.

    Parses template YAMLs once and reuses for both template and
    vocabulary extraction.
    """
    parsed_templates = _load_all_template_files(templates_dir)

    documents: list[dict[str, Any]] = []
    documents.extend(_extract_templates_from_parsed(parsed_templates))
    documents.extend(extract_generator_documents(generators_dir))
    documents.extend(extract_constraint_patterns())
    documents.extend(extract_linearization_techniques())
    documents.extend(extract_parser_capabilities())
    documents.extend(_extract_vocabulary_from_parsed(parsed_templates))
    logger.info("Total documents extracted: %d", len(documents))
    return documents
