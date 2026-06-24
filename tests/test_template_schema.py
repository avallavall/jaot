"""Tests for YAML template schema validation and loader.

Tests the Pydantic models for validating YAML template definitions,
the ModelCategory enum expansion, and the template file loader.
"""

import textwrap

import pytest
from pydantic import ValidationError

from app.models.optimization_model import ModelCategory


class TestModelCategoryEnum:
    """Test that ModelCategory enum has 25+ categories."""

    def test_enum_has_at_least_25_values(self):
        assert len(ModelCategory) >= 25

    def test_original_categories_preserved(self):
        original = [
            "FINANCE",
            "LOGISTICS",
            "MANUFACTURING",
            "AGRICULTURE",
            "HEALTHCARE",
            "ENERGY",
            "RETAIL",
            "HR",
            "GENERAL",
        ]
        for name in original:
            assert hasattr(ModelCategory, name), f"Missing original category: {name}"

    def test_new_categories_present(self):
        new_cats = [
            "SUPPLY_CHAIN",
            "FACILITY_LOCATION",
            "NETWORK_GRAPH",
            "CUTTING_PACKING",
            "TELECOM",
            "TRANSPORTATION",
            "ENVIRONMENTAL",
            "SPORTS",
            "EDUCATION",
            "REAL_ESTATE",
            "MINING",
            "WATER_MANAGEMENT",
            "AEROSPACE",
            "PHARMACEUTICAL",
            "CHEMICAL_ENGINEERING",
            "FORESTRY",
            "MARITIME",
            "RAILWAY",
            "FOOD_BEVERAGE",
            "TEXTILE",
            "CONSTRUCTION",
            "ADVERTISING_MEDIA",
            "WAREHOUSE",
            "INSURANCE",
            "GOVERNMENT",
        ]
        for name in new_cats:
            assert hasattr(ModelCategory, name), f"Missing new category: {name}"

    def test_all_values_are_lowercase_strings(self):
        for member in ModelCategory:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()


class TestTemplateDefinition:
    """Test Pydantic validation of template definitions."""

    def _valid_template_dict(self, **overrides):
        base = {
            "id": "test_template",
            "name": "Test Template",
            "display_name": "Test Template Display",
            "short_description": "A short description",
            "description": "A full description of the template",
            "category": "finance",
            "generator_type": "generic",
            "input_schema": {"type": "object", "properties": {}},
            "input_fields": [
                {
                    "name": "budget",
                    "label": "Budget",
                    "type": "number",
                    "description": "The budget amount",
                }
            ],
            "example_input": {"budget": 1000},
        }
        base.update(overrides)
        return base

    def test_valid_template_accepted(self):
        from app.data.templates._schema import TemplateDefinition

        data = self._valid_template_dict()
        td = TemplateDefinition(**data)
        assert td.id == "test_template"
        assert td.name == "Test Template"

    def test_missing_required_field_name(self):
        from app.data.templates._schema import TemplateDefinition

        data = self._valid_template_dict()
        del data["name"]
        with pytest.raises(ValidationError):
            TemplateDefinition(**data)

    def test_missing_required_field_generator_type(self):
        from app.data.templates._schema import TemplateDefinition

        data = self._valid_template_dict()
        del data["generator_type"]
        with pytest.raises(ValidationError):
            TemplateDefinition(**data)

    def test_missing_required_field_input_schema(self):
        from app.data.templates._schema import TemplateDefinition

        data = self._valid_template_dict()
        del data["input_schema"]
        with pytest.raises(ValidationError):
            TemplateDefinition(**data)

    def test_missing_required_field_example_input(self):
        from app.data.templates._schema import TemplateDefinition

        data = self._valid_template_dict()
        del data["example_input"]
        with pytest.raises(ValidationError):
            TemplateDefinition(**data)

    def test_invalid_category_logs_warning(self):
        from unittest.mock import patch

        from app.data.templates._schema import TemplateDefinition

        with patch("app.data.templates._schema.logger") as mock_logger:
            td = TemplateDefinition(**self._valid_template_dict(category="nonexistent_cat"))
        assert td.category == "nonexistent_cat"
        mock_logger.warning.assert_called_once()
        assert "nonexistent_cat" in str(mock_logger.warning.call_args)

    def test_tags_accept_industry_tags(self):
        from app.data.templates._schema import TemplateDefinition

        td = TemplateDefinition(**self._valid_template_dict(tags=["finance", "allocation", "roi"]))
        assert td.tags == ["finance", "allocation", "roi"]

    def test_problem_type_tags_accepted(self):
        from app.data.templates._schema import TemplateDefinition

        td = TemplateDefinition(
            **self._valid_template_dict(problem_type_tags=["LP", "MIP", "MILP"])
        )
        assert td.problem_type_tags == ["LP", "MIP", "MILP"]

    def test_size_estimate_fields_optional(self):
        from app.data.templates._schema import TemplateDefinition

        # Without size estimates
        td1 = TemplateDefinition(**self._valid_template_dict())
        assert td1.estimated_variables is None
        assert td1.estimated_constraints is None

        # With size estimates
        td2 = TemplateDefinition(
            **self._valid_template_dict(estimated_variables=50, estimated_constraints=30)
        )
        assert td2.estimated_variables == 50
        assert td2.estimated_constraints == 30

    def test_defaults_applied(self):
        from app.data.templates._schema import TemplateDefinition

        td = TemplateDefinition(**self._valid_template_dict())
        assert td.tags == []
        assert td.problem_type_tags == []
        assert td.is_featured is False
        assert td.version == "1.0.0"
        assert td.scenario_description == ""
        assert td.generator_params == {}


class TestLoadTemplatesFromYaml:
    """Test YAML loading and parsing."""

    def test_valid_yaml_parsed(self):
        from app.data.templates._schema import load_templates_from_yaml

        yaml_content = textwrap.dedent("""\
            category: finance
            category_display_name: Finance
            templates:
              - id: budget_test
                name: Budget Test
                display_name: Budget Test Display
                short_description: Short desc
                description: Full description
                category: finance
                generator_type: generic
                input_schema:
                  type: object
                  properties: {}
                input_fields:
                  - name: budget
                    label: Budget
                    type: number
                    description: The budget
                example_input:
                  budget: 1000
        """)
        result = load_templates_from_yaml(yaml_content)
        assert result.category == "finance"
        assert len(result.templates) == 1
        assert result.templates[0].id == "budget_test"

    def test_malformed_yaml_raises_error(self):
        import yaml

        from app.data.templates._schema import load_templates_from_yaml

        with pytest.raises(yaml.YAMLError):
            load_templates_from_yaml("{{{{invalid yaml: [")


class TestLoadAllTemplates:
    """Test auto-scanning of YAML files."""

    def test_load_from_empty_directory(self, tmp_path):
        from app.data.templates import load_all_templates

        result = load_all_templates(directory=tmp_path)
        assert result == []

    def test_load_from_directory_with_yaml(self, tmp_path):
        from app.data.templates import load_all_templates

        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            textwrap.dedent("""\
            category: finance
            category_display_name: Finance
            templates:
              - id: test1
                name: Test One
                display_name: Test One Display
                short_description: Short
                description: Full description
                category: finance
                generator_type: generic
                input_schema:
                  type: object
                  properties: {}
                input_fields:
                  - name: val
                    label: Value
                    type: number
                    description: A value
                example_input:
                  val: 42
              - id: test2
                name: Test Two
                display_name: Test Two Display
                short_description: Short 2
                description: Full description 2
                category: finance
                generator_type: generic
                input_schema:
                  type: object
                  properties: {}
                input_fields:
                  - name: val
                    label: Value
                    type: number
                    description: A value
                example_input:
                  val: 99
        """)
        )
        result = load_all_templates(directory=tmp_path)
        assert len(result) == 2
        ids = {t.id for t in result}
        assert ids == {"test1", "test2"}

    def test_invalid_yaml_file_skipped_with_warning(self, tmp_path):
        from unittest.mock import patch

        from app.data.templates import load_all_templates

        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{invalid yaml content [[[")

        with patch("app.data.templates.logger") as mock_logger:
            result = load_all_templates(directory=tmp_path)
        assert result == []
        mock_logger.warning.assert_called_once()
        assert "bad.yaml" in str(mock_logger.warning.call_args)
