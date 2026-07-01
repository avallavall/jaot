"""Tests for RAG document type extractors.

Covers all 6 document types: templates, generators, constraint patterns,
linearization techniques, parser capabilities, and industry vocabulary.
Tests both extraction correctness and contextual prefix application.
"""

from pathlib import Path

from app.services.rag.document_types import (
    DocType,
    _add_contextual_prefix,
    _load_yaml,
    _render_problem_compact,
    _synthesize_template_text,
    extract_all_documents,
    extract_constraint_patterns,
    extract_generator_documents,
    extract_industry_vocabulary,
    extract_linearization_techniques,
    extract_parser_capabilities,
    extract_template_documents,
    extract_worked_examples,
)


class TestDocTypeEnum:
    """DocType enum has all expected values."""

    def test_all_types_defined(self):
        expected = {
            "template",
            "generator",
            "constraint_pattern",
            "linearization",
            "parser_capability",
            "industry_vocabulary",
            "worked_example",
        }
        actual = {dt.value for dt in DocType}
        assert actual == expected


# _load_yaml helper


class TestLoadYaml:
    """YAML loader handles valid files, missing files, and malformed YAML."""

    def test_loads_valid_yaml(self, tmp_path: Path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nitems:\n  - one\n  - two\n")
        result = _load_yaml(yaml_file, "test")
        assert result == {"key": "value", "items": ["one", "two"]}

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        result = _load_yaml(tmp_path / "nonexistent.yaml", "missing")
        assert result is None

    def test_returns_none_for_malformed_yaml(self, tmp_path: Path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("{{invalid: yaml: [[[")
        result = _load_yaml(yaml_file, "bad")
        assert result is None


class TestContextualPrefix:
    """Each doc type gets a descriptive prefix for better embedding retrieval."""

    def test_template_prefix(self):
        result = _add_contextual_prefix(
            "body text", DocType.TEMPLATE, "Logistics problems involving Knapsack"
        )
        assert result.startswith("This is a JAOT optimization template for Logistics")
        assert "body text" in result

    def test_generator_prefix(self):
        result = _add_contextual_prefix("body text", DocType.GENERATOR, "routing")
        assert "code generator for routing" in result

    def test_constraint_pattern_prefix(self):
        result = _add_contextual_prefix("body text", DocType.CONSTRAINT_PATTERN, "Capacity")
        assert "constraint pattern called Capacity" in result

    def test_linearization_prefix(self):
        result = _add_contextual_prefix("body text", DocType.LINEARIZATION, "Big-M")
        assert "linearization technique called Big-M" in result

    def test_parser_capability_prefix(self):
        result = _add_contextual_prefix(
            "body text", DocType.PARSER_CAPABILITY, "Supported Operators"
        )
        assert "parser capabilities: Supported Operators" in result

    def test_industry_vocabulary_prefix(self):
        result = _add_contextual_prefix("body text", DocType.INDUSTRY_VOCABULARY, "Healthcare")
        assert "terminology from Healthcare" in result


# Template extraction (from real YAML files)


class TestExtractTemplateDocuments:
    """Template extractor reads all YAML files and produces correct documents."""

    def test_extracts_from_real_templates(self):
        docs = extract_template_documents()
        assert len(docs) >= 100  # We have 102 templates

    def test_each_doc_has_required_fields(self):
        docs = extract_template_documents()
        for doc in docs[:5]:  # Spot-check first 5
            assert doc["id"].startswith("tmpl_")
            assert doc["text"]
            assert doc["payload"]["doc_type"] == DocType.TEMPLATE.value
            assert doc["payload"]["template_id"]
            assert doc["payload"]["category"]
            assert doc["payload"]["generator_type"]

    def test_contextual_prefix_applied(self):
        docs = extract_template_documents()
        for doc in docs[:5]:
            assert doc["text"].startswith("This is a JAOT optimization template")

    def test_archetype_field_present(self):
        docs = extract_template_documents()
        knapsack_docs = [d for d in docs if d["payload"]["template_id"] == "knapsack"]
        assert len(knapsack_docs) >= 1
        assert "Archetype:" in knapsack_docs[0]["text"]
        assert "0-1 knapsack" in knapsack_docs[0]["text"]

    def test_disambiguation_present_for_known_types(self):
        docs = extract_template_documents()
        knapsack_docs = [d for d in docs if d["payload"]["template_id"] == "knapsack"]
        assert any("Not to be confused with" in d["text"] for d in knapsack_docs)

    def test_handles_missing_directory(self, tmp_path: Path):
        docs = extract_template_documents(tmp_path / "nonexistent")
        assert docs == []


class TestSynthesizeTemplateText:
    """Template text synthesis includes all expected sections."""

    def test_includes_display_name_and_category(self):
        template = {
            "display_name": "Test Template",
            "generator_type": "knapsack",
            "problem_type_tags": ["MIP"],
            "short_description": "A test template.",
            "description": "Full description here.",
            "tags": ["test", "sample"],
        }
        text = _synthesize_template_text(template, "Test Category")
        assert "Template: Test Template" in text
        assert "Category: Test Category" in text
        assert "Problem Type: MIP" in text
        assert "Summary: A test template." in text
        assert "Keywords: test, sample" in text
        assert "Generator: knapsack" in text

    def test_handles_missing_optional_fields(self):
        template = {"name": "Minimal", "generator_type": "generic"}
        text = _synthesize_template_text(template, "General")
        assert "Template: Minimal" in text
        assert "Category: General" in text
        # Optional fields must be omitted, not stringified as 'None' or
        # rendered as bare 'Keywords:' headers with no content
        assert "Keywords:" not in text
        assert "None" not in text


# Generator extraction (from real Python files)


class TestExtractGeneratorDocuments:
    """Generator extractor reads Python files and extracts docstrings."""

    def test_extracts_from_real_generators(self):
        docs = extract_generator_documents()
        assert len(docs) >= 20  # We have 26 generators

    def test_each_doc_has_required_fields(self):
        docs = extract_generator_documents()
        for doc in docs[:5]:
            assert doc["id"].startswith("gen_")
            assert doc["text"]
            assert doc["payload"]["doc_type"] == DocType.GENERATOR.value
            assert doc["payload"]["generator_type"]
            assert doc["payload"]["source_file"]

    def test_skips_base_and_private_files(self):
        docs = extract_generator_documents()
        ids = [d["id"] for d in docs]
        assert "gen_base" not in ids
        assert "gen___init__" not in ids

    def test_contextual_prefix_applied(self):
        docs = extract_generator_documents()
        for doc in docs[:5]:
            assert doc["text"].startswith("This is a JAOT code generator")

    def test_knapsack_generator_has_docstring(self):
        docs = extract_generator_documents()
        knapsack = [d for d in docs if d["payload"]["generator_type"] == "knapsack"]
        assert len(knapsack) == 1
        assert "Description:" in knapsack[0]["text"]


# Constraint patterns (from YAML)


class TestExtractConstraintPatterns:
    """Constraint pattern extractor reads the YAML data file."""

    def test_extracts_all_patterns(self):
        docs = extract_constraint_patterns()
        assert len(docs) == 12  # 2 original + 10 new

    def test_each_doc_has_required_fields(self):
        docs = extract_constraint_patterns()
        for doc in docs:
            assert doc["id"].startswith("cstr_")
            assert doc["payload"]["doc_type"] == DocType.CONSTRAINT_PATTERN.value
            assert doc["payload"]["pattern_name"]
            assert "Canonical Form:" in doc["text"] or "Constraint Pattern:" in doc["text"]

    def test_capacity_pattern_exists(self):
        docs = extract_constraint_patterns()
        capacity = [d for d in docs if d["payload"]["pattern_id"] == "capacity"]
        assert len(capacity) == 1
        assert "sum(weight_i * x_i) <= capacity" in capacity[0]["text"]

    def test_contextual_prefix_applied(self):
        docs = extract_constraint_patterns()
        for doc in docs:
            assert doc["text"].startswith("This is a reusable constraint pattern")

    def test_handles_missing_file(self, tmp_path: Path):
        docs = extract_constraint_patterns(tmp_path / "nonexistent.yaml")
        assert docs == []


# Linearization techniques (from YAML)


class TestExtractLinearizationTechniques:
    """Linearization technique extractor reads the YAML data file."""

    def test_extracts_all_techniques(self):
        docs = extract_linearization_techniques()
        assert len(docs) == 7

    def test_each_doc_has_required_fields(self):
        docs = extract_linearization_techniques()
        for doc in docs:
            assert doc["id"].startswith("lin_")
            assert doc["payload"]["doc_type"] == DocType.LINEARIZATION.value
            assert doc["payload"]["technique_name"]

    def test_product_of_binaries_exists(self):
        docs = extract_linearization_techniques()
        product = [d for d in docs if d["payload"]["technique_id"] == "product_of_binaries"]
        assert len(product) == 1
        assert "z = x * y" in product[0]["text"]

    def test_big_m_calibration_exists(self):
        docs = extract_linearization_techniques()
        big_m = [d for d in docs if d["payload"]["technique_id"] == "big_m_calibration"]
        assert len(big_m) == 1

    def test_contextual_prefix_applied(self):
        docs = extract_linearization_techniques()
        for doc in docs:
            assert doc["text"].startswith("This is a linearization technique")


# Parser capabilities (from YAML)


class TestExtractParserCapabilities:
    """Parser capability extractor reads the YAML data file."""

    def test_extracts_all_capabilities(self):
        docs = extract_parser_capabilities()
        assert len(docs) == 5

    def test_each_doc_has_required_fields(self):
        docs = extract_parser_capabilities()
        for doc in docs:
            assert doc["id"].startswith("parser_")
            assert doc["payload"]["doc_type"] == DocType.PARSER_CAPABILITY.value
            assert doc["payload"]["title"]

    def test_limitations_doc_exists(self):
        docs = extract_parser_capabilities()
        limitations = [d for d in docs if "limitation" in d["payload"]["title"].lower()]
        assert len(limitations) == 1
        assert "NOT support" in limitations[0]["text"]


# Industry vocabulary (from template YAML files)


class TestExtractIndustryVocabulary:
    """Industry vocabulary extractor synthesizes from template categories."""

    def test_extracts_from_real_templates(self):
        docs = extract_industry_vocabulary()
        assert len(docs) >= 30  # We have 34+ categories

    def test_each_doc_has_required_fields(self):
        docs = extract_industry_vocabulary()
        for doc in docs[:5]:
            assert doc["id"].startswith("vocab_")
            assert doc["payload"]["doc_type"] == DocType.INDUSTRY_VOCABULARY.value
            assert doc["payload"]["category"]
            assert doc["payload"]["generator_types"]

    def test_logistics_vocabulary_exists(self):
        docs = extract_industry_vocabulary()
        logistics = [d for d in docs if d["payload"]["category"] == "logistics"]
        assert len(logistics) == 1
        assert "knapsack" in logistics[0]["text"].lower()

    def test_contextual_prefix_applied(self):
        docs = extract_industry_vocabulary()
        for doc in docs[:5]:
            assert doc["text"].startswith("This maps industry-specific terminology")


# worked examples


class TestRenderProblemCompact:
    """The compact renderer bounds size and reports omitted items."""

    def test_small_problem_rendered_in_full(self):
        problem = {
            "variables": [
                {"name": "x", "type": "integer", "lower_bound": 0, "upper_bound": 100},
                {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": None},
            ],
            "objective": {"sense": "minimize", "expression": "3*x + 5*y"},
            "constraints": [{"name": "cap", "expression": "x + y <= 10"}],
        }
        text = _render_problem_compact(problem)
        assert "Variables (2 total): x (integer, [0, 100]); y (continuous, [0, +inf])" in text
        assert "Objective: minimize 3*x + 5*y" in text
        assert "Constraints (1 total):" in text
        assert "cap: x + y <= 10" in text
        assert "more)" not in text  # nothing omitted

    def test_binary_variable_omits_noisy_bounds(self):
        problem = {
            "variables": [{"name": "use_a", "type": "binary", "upper_bound": None}],
            "objective": {"sense": "maximize", "expression": "use_a"},
            "constraints": [],
        }
        text = _render_problem_compact(problem)
        assert "use_a (binary)" in text
        assert "[-inf, +inf]" not in text  # binary domain is implicit, no noisy bounds

    def test_large_problem_is_truncated_with_omitted_note(self):
        problem = {
            "variables": [
                {"name": f"x{i}", "type": "binary", "lower_bound": 0, "upper_bound": 1}
                for i in range(200)
            ],
            "objective": {"sense": "maximize", "expression": "z"},
            "constraints": [{"name": f"c{i}", "expression": f"x{i} <= 1"} for i in range(200)],
        }
        text = _render_problem_compact(problem)
        # Totals reflect the FULL problem; only the rendered head is truncated.
        assert "Variables (200 total):" in text
        assert "Constraints (200 total):" in text
        assert "(+175 more)" in text  # 200 - 25 head

    def test_long_expression_is_clipped(self):
        problem = {
            "variables": [{"name": "x", "type": "continuous"}],
            "objective": {"sense": "minimize", "expression": "a" * 5000},
            "constraints": [],
        }
        text = _render_problem_compact(problem)
        assert "chars)" in text  # elision marker
        assert len(text) < 1000  # the 5000-char expression was clipped


class TestExtractWorkedExamples:
    """Worked examples render real formulations from each template's example_input."""

    def test_produces_worked_example_docs(self):
        docs = extract_worked_examples()
        assert len(docs) > 0, "expected at least one template to render a worked example"
        for doc in docs:
            assert doc["payload"]["doc_type"] == DocType.WORKED_EXAMPLE.value
            assert doc["id"].startswith("example_")
            assert doc["payload"]["template_id"]
            assert doc["payload"]["generator_type"]

    def test_worked_example_text_shape(self):
        docs = extract_worked_examples()
        doc = docs[0]
        # Contextual prefix + the compact formulation sections.
        assert doc["text"].startswith("This ")
        assert "Worked example:" in doc["text"]
        assert "Variables (" in doc["text"]
        assert "Objective:" in doc["text"]

    def test_ids_are_unique(self):
        docs = extract_worked_examples()
        ids = [d["id"] for d in docs]
        assert len(ids) == len(set(ids))


# extract_all_documents


class TestExtractAllDocuments:
    """Full extraction produces all document types with correct totals."""

    def test_total_count(self):
        docs = extract_all_documents()
        # 186 base docs (templates + generators + constraint patterns + linearization
        # + parser capabilities + vocabulary) plus one worked example per template that
        # renders from its example_input. The base stays pinned; worked examples float.
        worked = [d for d in docs if d["payload"]["doc_type"] == DocType.WORKED_EXAMPLE.value]
        assert len(worked) > 0, "expected worked-example docs to be extracted"
        assert len(docs) == 186 + len(worked)

    def test_all_doc_types_present(self):
        docs = extract_all_documents()
        types = {d["payload"]["doc_type"] for d in docs}
        expected = {dt.value for dt in DocType}
        assert types == expected

    def test_no_duplicate_ids(self):
        docs = extract_all_documents()
        ids = [d["id"] for d in docs]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"

    def test_all_docs_have_text(self):
        docs = extract_all_documents()
        for doc in docs:
            assert doc["text"], f"Empty text for {doc['id']}"
            assert len(doc["text"]) > 20, f"Suspiciously short text for {doc['id']}"

    def test_all_docs_have_contextual_prefix(self):
        docs = extract_all_documents()
        for doc in docs:
            assert doc["text"].startswith("This "), (
                f"Missing contextual prefix for {doc['id']}: {doc['text'][:50]}"
            )
