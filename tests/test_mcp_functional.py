"""MCP tools functional tests (Task 3.6).

Validates that MCP-exposed endpoints actually WORK (not just exist):
- list_templates returns actual template data
- get_template with valid ID returns template details
- get_template with invalid ID returns 404
- validate_problem with valid problem returns validation result
- validate_problem with invalid problem returns errors
- list_catalog_models returns published models from DB
- list_catalog_models excludes unpublished/private models

These tests use the real PostgreSQL test database (not mocks).
"""

import pytest

from app.domains.solver.services.generators import GENERATOR_REGISTRY
from app.models import ModelCatalog, ModelCategory


@pytest.fixture
def published_catalog_model(db_session):
    """Create a published, public catalog model in the DB."""
    model = ModelCatalog(
        id="mcp_test_model_001",
        name="mcp_test_knapsack",
        display_name="MCP Test Knapsack",
        description="A test model used by MCP functional tests",
        short_description="Test knapsack",
        category=ModelCategory.LOGISTICS,
        tags=["test", "mcp"],
        generator_type="knapsack",
        input_schema={"type": "object", "properties": {"capacity": {"type": "number"}}},
        input_fields=[{"name": "capacity", "type": "number", "label": "Capacity"}],
        example_input={"capacity": 100},
        version="1.0.0",
        status="published",
        is_official=True,
        is_public=True,
        price_eur=0.0,
        credits_per_execution=1,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


@pytest.fixture
def draft_catalog_model(db_session):
    """Create a draft (unpublished) catalog model in the DB."""
    model = ModelCatalog(
        id="mcp_test_draft_001",
        name="mcp_test_draft",
        display_name="MCP Test Draft",
        description="A draft model that should NOT appear in catalog",
        category=ModelCategory.GENERAL,
        generator_type="generic",
        input_schema={},
        input_fields=[],
        example_input={},
        version="1.0.0",
        status="draft",
        is_official=False,
        is_public=True,
        price_eur=0.0,
        credits_per_execution=1,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


@pytest.fixture
def private_catalog_model(db_session):
    """Create a published but private catalog model in the DB."""
    model = ModelCatalog(
        id="mcp_test_private_001",
        name="mcp_test_private",
        display_name="MCP Test Private",
        description="A private model that should NOT appear in public catalog",
        category=ModelCategory.GENERAL,
        generator_type="generic",
        input_schema={},
        input_fields=[],
        example_input={},
        version="1.0.0",
        status="published",
        is_official=False,
        is_public=False,
        price_eur=0.0,
        credits_per_execution=1,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


VALID_PROBLEM = {
    "name": "mcp_test_linear",
    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0},
        {"name": "y", "type": "continuous", "lower_bound": 0},
    ],
    "constraints": [
        {"name": "c1", "expression": "x + y <= 4"},
        {"name": "c2", "expression": "2*x + y <= 5"},
    ],
}


# 1. list_templates — returns actual template data


class TestListTemplates:
    """Tests for GET /api/v2/solve/templates (list_templates MCP tool)."""

    def test_list_templates_returns_templates(self, client):
        """list_templates returns a non-empty list of templates with required fields."""
        response = client.get("/api/v2/solve/templates")
        assert response.status_code == 200

        data = response.json()
        assert "templates" in data
        assert len(data["templates"]) > 0, "Expected at least one built-in template"

    def test_list_templates_returns_all_yaml_templates(self, client):
        """list_templates returns all YAML-defined templates (~102 total)."""
        response = client.get("/api/v2/solve/templates")
        data = response.json()

        assert "total" in data, "Response should include 'total' count"
        assert data["total"] >= 100, f"Expected >= 100 templates, got {data['total']}"
        assert len(data["templates"]) == data["total"]

    def test_list_templates_includes_yaml_templates(self, client):
        """YAML-only templates like nurse_scheduling should appear in list."""
        response = client.get("/api/v2/solve/templates")
        data = response.json()

        ids = {t["id"] for t in data["templates"]}
        yaml_only = {"nurse_scheduling", "demand_allocation", "store_layout"}
        missing = yaml_only - ids
        assert not missing, f"YAML templates missing from list: {missing}"

    def test_list_templates_contains_required_fields(self, client):
        """Each template has all required fields including new enriched ones."""
        response = client.get("/api/v2/solve/templates")
        data = response.json()

        required_fields = {
            "id",
            "name",
            "display_name",
            "description",
            "category",
            "tags",
            "short_description",
            "problem_type_tags",
            "generator_type",
            "is_featured",
            "estimated_variables",
            "estimated_constraints",
        }
        for template in data["templates"]:
            missing = required_fields - set(template.keys())
            assert not missing, f"Template {template.get('id', '?')} missing fields: {missing}"

    def test_list_templates_includes_known_template(self, client):
        """The built-in 'budget_allocation' template should be present."""
        response = client.get("/api/v2/solve/templates")
        data = response.json()

        template_ids = [t["id"] for t in data["templates"]]
        assert "budget_allocation" in template_ids, (
            f"Expected 'budget_allocation' in templates, found: {template_ids}"
        )

    def test_list_templates_tags_are_lists(self, client):
        """Template tags should be lists of strings."""
        response = client.get("/api/v2/solve/templates")
        data = response.json()

        for template in data["templates"]:
            assert isinstance(template["tags"], list), (
                f"Template {template['id']} tags should be a list"
            )

    def test_list_templates_filter_by_category(self, client):
        """?category= filter returns only templates in that category."""
        response = client.get("/api/v2/solve/templates?category=healthcare")
        data = response.json()

        assert data["total"] > 0, "healthcare category should have templates"
        for t in data["templates"]:
            assert t["category"] == "healthcare", (
                f"Template {t['id']} has category {t['category']}, expected healthcare"
            )

    def test_list_templates_filter_by_featured(self, client):
        """?featured=true returns only featured templates."""
        response = client.get("/api/v2/solve/templates?featured=true")
        data = response.json()

        assert data["total"] > 0, "Should have at least one featured template"
        for t in data["templates"]:
            assert t["is_featured"] is True, (
                f"Template {t['id']} is not featured but was returned with ?featured=true"
            )

    def test_list_templates_filter_empty_category(self, client):
        """?category= with nonexistent category returns empty list."""
        response = client.get("/api/v2/solve/templates?category=nonexistent_xyz")
        data = response.json()

        assert data["total"] == 0
        assert data["templates"] == []


# 2. get_template — with valid and invalid IDs


class TestGetTemplate:
    """Tests for GET /api/v2/solve/templates/{template_id} (get_template MCP tool)."""

    def test_get_template_valid_id(self, client):
        """get_template with a known built-in template ID returns full details."""
        response = client.get("/api/v2/solve/templates/budget_allocation")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "budget_allocation"
        assert "input_fields" in data
        assert "example_input" in data
        assert len(data["input_fields"]) > 0, "Template should have input fields"

    def test_get_template_returns_enriched_yaml_data(self, client):
        """Templates return enriched YAML metadata (short_description, etc.)."""
        response = client.get("/api/v2/solve/templates/knapsack")
        assert response.status_code == 200

        data = response.json()
        assert "short_description" in data
        assert data["short_description"] is not None

    def test_get_template_yaml_id(self, client):
        """Any YAML-defined template is resolved correctly."""
        response = client.get("/api/v2/solve/templates/nurse_scheduling")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "nurse_scheduling"
        assert data["category"] == "healthcare"
        assert "input_fields" in data
        assert "example_input" in data

    def test_get_template_returns_example_input(self, client):
        """get_template returns a non-empty example_input for knapsack template."""
        response = client.get("/api/v2/solve/templates/knapsack")
        assert response.status_code == 200

        data = response.json()
        assert data["example_input"] is not None
        assert len(data["example_input"]) > 0, "example_input should be non-empty"

    def test_get_template_invalid_id_returns_404(self, client):
        """get_template with a non-existent template ID returns 404."""
        response = client.get("/api/v2/solve/templates/nonexistent_template_xyz")
        assert response.status_code == 404

    def test_get_template_fallback_to_db(self, client, db_session, published_catalog_model):
        """get_template falls back to DB ModelCatalog when not in YAML."""
        response = client.get(f"/api/v2/solve/templates/{published_catalog_model.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == published_catalog_model.id
        assert data["display_name"] == published_catalog_model.display_name

    def test_get_template_db_fallback_draft_returns_404(
        self, client, db_session, draft_catalog_model
    ):
        """get_template DB fallback rejects draft (unpublished) models with 404."""
        response = client.get(f"/api/v2/solve/templates/{draft_catalog_model.id}")
        assert response.status_code == 404

    def test_diet_optimization_has_correct_category(self, client):
        """diet_optimization must have category 'healthcare', not 'health'."""
        response = client.get("/api/v2/solve/templates/diet_optimization")
        assert response.status_code == 200

        data = response.json()
        assert data["category"] == "healthcare", (
            f"diet_optimization category should be 'healthcare', got '{data['category']}'"
        )

    def test_diet_optimization_uses_blending_generator(self, client):
        """diet_optimization uses blending generator with domain-friendly input."""
        response = client.get("/api/v2/solve/templates/diet_optimization")
        data = response.json()

        assert data["generator_type"] == "blending"
        field_names = {f["name"] for f in data["input_fields"]}
        assert "ingredients" in field_names, "diet should have 'ingredients' field"
        assert "targets" in field_names, "diet should have 'targets' field"
        # Must NOT have raw LP fields
        assert "objective" not in field_names, "diet should not have raw 'objective' field"
        assert "variables" not in field_names, "diet should not have raw 'variables' field"


# 2b. Every template is accessible via API


def _all_template_ids() -> list[str]:
    """Collect every template ID from YAML definitions."""
    from app.data.templates import load_all_templates

    return [t.id for t in load_all_templates()]


_VALID_CATEGORIES = {m.value for m in ModelCategory}
_VALID_GENERATORS = set(GENERATOR_REGISTRY.list_generators())


@pytest.mark.parametrize("template_id", _all_template_ids())
def test_every_template_accessible_via_api(client, template_id):
    """Each template is fetchable and has a coherent, complete structure."""
    response = client.get(f"/api/v2/solve/templates/{template_id}")
    assert response.status_code == 200, f"Template '{template_id}' returned {response.status_code}"

    data = response.json()
    t = template_id  # short alias for error messages

    # --- Identity ---
    assert data["id"] == template_id
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0, f"{t}: empty name"
    assert isinstance(data.get("display_name"), str) and len(data["display_name"]) > 0, (
        f"{t}: empty display_name"
    )
    assert isinstance(data.get("description"), str) and len(data["description"]) > 10, (
        f"{t}: description too short or missing"
    )

    # --- Category belongs to ModelCategory enum ---
    assert data.get("category") in _VALID_CATEGORIES, (
        f"{t}: category '{data.get('category')}' not in ModelCategory enum"
    )

    # --- Generator is registered ---
    gen = data.get("generator") or data.get("generator_type")
    assert gen in _VALID_GENERATORS, f"{t}: generator '{gen}' not in GENERATOR_REGISTRY"

    # --- Tags are a non-empty list of strings ---
    tags = data.get("tags", [])
    assert isinstance(tags, list) and len(tags) > 0, f"{t}: tags should be a non-empty list"
    assert all(isinstance(tag, str) for tag in tags), f"{t}: tags contain non-string values"

    # --- Input fields: non-empty, each has name/type/label ---
    fields = data.get("input_fields", [])
    assert len(fields) > 0, f"{t}: no input_fields"
    for field in fields:
        assert "name" in field, f"{t}: input_field missing 'name'"
        assert "type" in field, f"{t}: input_field '{field.get('name')}' missing 'type'"

    # --- Example input: non-empty, keys overlap with input_fields ---
    example = data.get("example_input", {})
    assert len(example) > 0, f"{t}: empty example_input"

    # For non-generic generators, example keys should match field names
    if gen != "generic":
        field_names = {f["name"] for f in fields}
        example_keys = set(example.keys())
        overlap = field_names & example_keys
        assert len(overlap) > 0, (
            f"{t}: example_input keys {example_keys} don't overlap "
            f"with input_field names {field_names}"
        )


# 2c. Template resolution by source type (YAML, plugin-only, DB)


class TestTemplateResolutionBySource:
    """Each template source (YAML, DB) resolves correctly via API."""

    def test_yaml_template_resolves(self, client):
        """YAML-only template (nurse_scheduling) returns full enriched data."""
        response = client.get("/api/v2/solve/templates/nurse_scheduling")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "nurse_scheduling"
        assert data["category"] == "healthcare"
        assert data["generator_type"] == "scheduling"
        # YAML-specific enriched fields
        assert data["short_description"] is not None
        assert data["scenario_description"] is not None
        assert data["is_featured"] is True
        assert data["estimated_variables"] == 112
        assert len(data["input_fields"]) > 0
        assert len(data["example_input"]) > 0

    def test_assignment_template_resolves_from_yaml(self, client):
        """assignment template (formerly plugin-only) resolves from YAML."""
        response = client.get("/api/v2/solve/templates/assignment")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "assignment"
        assert data["category"] == "hr"
        assert data["generator_type"] == "assignment"
        assert data["short_description"] is not None, (
            "Should come from YAML (has short_description)"
        )
        assert len(data["input_fields"]) > 0
        assert len(data["example_input"]) > 0

    def test_db_only_template_resolves(self, client, db_session, published_catalog_model):
        """DB-only template (not in YAML or plugin) resolves via catalog fallback."""
        response = client.get(f"/api/v2/solve/templates/{published_catalog_model.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == published_catalog_model.id
        assert data["display_name"] == published_catalog_model.display_name
        assert data["generator_type"] == published_catalog_model.generator_type

    def test_yaml_template_has_enriched_metadata(self, client):
        """YAML templates include enriched metadata fields."""
        response = client.get("/api/v2/solve/templates/budget_allocation")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "budget_allocation"
        assert data["short_description"] is not None
        assert data["scenario_description"] is not None
        assert "problem_type_tags" in data

    def test_resolution_order_yaml_then_db(self, client, db_session):
        """Resolution priority: YAML > DB."""
        # YAML template — must NOT fall through to DB even if seeded there
        response = client.get("/api/v2/solve/templates/knapsack")
        data = response.json()
        assert data.get("estimated_variables") is not None, (
            "knapsack should resolve from YAML (has estimated_variables)"
        )

        # Nonexistent template — both sources miss → 404
        response = client.get("/api/v2/solve/templates/totally_fake_xyz")
        assert response.status_code == 404


# 3. validate_problem — valid and invalid problems


class TestValidateProblem:
    """Tests for POST /api/v2/solve/validate (validate_problem MCP tool)."""

    def test_validate_valid_problem(self, client):
        """validate_problem with a well-formed problem returns valid=True."""
        response = client.post("/api/v2/solve/validate", json=VALID_PROBLEM)
        assert response.status_code == 200

        data = response.json()
        assert data["valid"] is True
        assert "estimated_credits" in data
        assert data["num_variables"] == 2
        assert data["num_constraints"] == 2

    def test_validate_returns_variable_type_breakdown(self, client):
        """validate_problem returns a breakdown of variable types."""
        response = client.post("/api/v2/solve/validate", json=VALID_PROBLEM)
        assert response.status_code == 200

        data = response.json()
        assert "variable_types" in data
        assert data["variable_types"]["continuous"] == 2
        assert data["variable_types"]["integer"] == 0
        assert data["variable_types"]["binary"] == 0

    def test_validate_mixed_variable_types(self, client):
        """validate_problem correctly counts mixed variable types."""
        problem = {
            "name": "mixed_vars",
            "objective": {"sense": "maximize", "expression": "x + y + z"},
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0},
                {"name": "y", "type": "integer", "lower_bound": 0, "upper_bound": 10},
                {"name": "z", "type": "binary"},
            ],
            "constraints": [
                {"name": "c1", "expression": "x + y + z <= 10"},
            ],
        }
        response = client.post("/api/v2/solve/validate", json=problem)
        assert response.status_code == 200

        data = response.json()
        assert data["valid"] is True
        assert data["variable_types"]["continuous"] == 1
        assert data["variable_types"]["integer"] == 1
        assert data["variable_types"]["binary"] == 1

    def test_validate_empty_problem_returns_422(self, client):
        """validate_problem with empty body returns 422 (validation error)."""
        response = client.post("/api/v2/solve/validate", json={})
        assert response.status_code == 422

    def test_validate_missing_variables_returns_422(self, client):
        """validate_problem missing required 'variables' field returns 422."""
        incomplete = {
            "name": "incomplete",
            "objective": {"sense": "maximize", "expression": "x"},
            "constraints": [],
        }
        response = client.post("/api/v2/solve/validate", json=incomplete)
        assert response.status_code == 422

    def test_validate_credits_estimate_scales_with_complexity(self, client):
        """Larger problems should have higher credit estimates."""
        small_problem = {
            "name": "small",
            "objective": {"sense": "minimize", "expression": "x"},
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
            "constraints": [{"name": "c1", "expression": "x >= 1"}],
        }
        large_problem = {
            "name": "large",
            "objective": {
                "sense": "minimize",
                "expression": " + ".join(f"v{i}" for i in range(20)),
            },
            "variables": [
                {"name": f"v{i}", "type": "integer", "lower_bound": 0, "upper_bound": 100}
                for i in range(20)
            ],
            "constraints": [{"name": f"c{i}", "expression": f"v{i} <= 50"} for i in range(20)],
        }

        small_resp = client.post("/api/v2/solve/validate", json=small_problem)
        large_resp = client.post("/api/v2/solve/validate", json=large_problem)

        assert small_resp.status_code == 200
        assert large_resp.status_code == 200

        small_credits = small_resp.json()["estimated_credits"]
        large_credits = large_resp.json()["estimated_credits"]
        assert large_credits > small_credits, (
            f"Large problem ({large_credits} credits) should cost more than "
            f"small problem ({small_credits} credits)"
        )


# 4. list_catalog_models — returns published models


class TestListCatalogModels:
    """Tests for GET /api/v2/models/catalog (list_catalog_models MCP tool)."""

    def test_list_catalog_returns_published_models(
        self, client, db_session, published_catalog_model
    ):
        """list_catalog_models includes published public models."""
        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        data = response.json()
        assert "items" in data
        assert "total" in data

        model_ids = [item["id"] for item in data["items"]]
        assert published_catalog_model.id in model_ids

    def test_list_catalog_excludes_draft_models(self, client, db_session, draft_catalog_model):
        """list_catalog_models excludes unpublished (draft) models."""
        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        data = response.json()
        model_ids = [item["id"] for item in data["items"]]
        assert draft_catalog_model.id not in model_ids

    def test_list_catalog_excludes_private_models(self, client, db_session, private_catalog_model):
        """list_catalog_models excludes private (is_public=False) models."""
        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        data = response.json()
        model_ids = [item["id"] for item in data["items"]]
        assert private_catalog_model.id not in model_ids

    def test_list_catalog_model_has_required_fields(
        self, client, db_session, published_catalog_model
    ):
        """Each catalog model response contains expected fields."""
        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        data = response.json()
        test_model = next(
            (item for item in data["items"] if item["id"] == published_catalog_model.id),
            None,
        )
        assert test_model is not None, "Test model not found in catalog response"
        assert test_model["display_name"] == "MCP Test Knapsack"
        assert test_model["category"] == "logistics"
        assert test_model["is_official"] is True

    def test_list_catalog_empty_db(self, client, db_session):
        """list_catalog_models returns empty list when no published models exist."""
        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 0
        assert isinstance(data["items"], list)

    def test_list_catalog_pagination_metadata(self, client, db_session, published_catalog_model):
        """list_catalog_models returns pagination metadata."""
        response = client.get("/api/v2/models/catalog?page=1&page_size=5")
        assert response.status_code == 200

        data = response.json()
        assert "page" in data
        assert "page_size" in data
        assert "total_pages" in data
        assert data["page"] == 1
        assert data["page_size"] == 5


class TestCatalogErrorResponses:
    """Tests for error responses on catalog MCP tools."""

    def test_get_catalog_model_not_found(self, client):
        """GET /models/catalog/{bad_id} returns 404."""
        response = client.get("/api/v2/models/catalog/nonexistent_model_xyz")
        assert response.status_code == 404

    def test_get_catalog_model_schema_not_found(self, client):
        """GET /models/catalog/{bad_id}/schema returns 404."""
        response = client.get("/api/v2/models/catalog/nonexistent_model_xyz/schema")
        assert response.status_code == 404

    def test_get_catalog_model_draft_not_visible(self, client, db_session, draft_catalog_model):
        """GET /models/catalog/{draft_id} returns 404 for draft models."""
        response = client.get(f"/api/v2/models/catalog/{draft_catalog_model.id}")
        assert response.status_code == 404

    def test_get_catalog_model_schema_for_published(
        self, client, db_session, published_catalog_model
    ):
        """GET /models/catalog/{id}/schema returns schema data for published model."""
        response = client.get(f"/api/v2/models/catalog/{published_catalog_model.id}/schema")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == published_catalog_model.id
        assert "input_schema" in data
        assert "example_input" in data
        assert data["generator_type"] == "knapsack"
