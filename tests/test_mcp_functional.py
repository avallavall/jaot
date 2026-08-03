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
from app.models import (
    ModelCategory,
    ModelProject,
    ModelProjectListing,
    Organization,
)


def _plant_listing(db, *, model_id: str, **fields) -> ModelProjectListing:
    """Plant a marketplace model: the project plus the listing facet served to callers.

    Since the P1.5 fusion the marketplace and MCP catalog tools read
    ``ModelProjectListing``; D-26 removed the pre-fusion ``ModelCatalog`` these
    fixtures used to mirror from, which was never what the endpoints queried.
    """
    org_id = "org_mcp_test"
    if not db.query(Organization).filter(Organization.id == org_id).first():
        db.add(Organization(id=org_id, name="MCP Test Org"))
        db.flush()
    db.add(
        ModelProject(
            id=model_id,
            organization_id=org_id,
            name=fields["display_name"],
            status="active",
        )
    )
    db.flush()
    listing = ModelProjectListing(model_project_id=model_id, **fields)
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


@pytest.fixture
def published_catalog_model(db_session):
    """A published, public marketplace model."""
    return _plant_listing(
        db_session,
        model_id="mcp_test_model_001",
        name="mcp_test_knapsack",
        display_name="MCP Test Knapsack",
        description="A test model used by MCP functional tests",
        short_description="Test knapsack",
        category=ModelCategory.LOGISTICS.value,
        tags=["test", "mcp"],
        generator_type="knapsack",
        input_schema={"type": "object", "properties": {"capacity": {"type": "number"}}},
        input_fields=[{"name": "capacity", "type": "number", "label": "Capacity"}],
        example_input={"capacity": 100},
        version="1.0.0",
        status="published",
        is_official=True,
        is_public=True,
    )


@pytest.fixture
def draft_catalog_model(db_session):
    """A draft (unpublished) marketplace model — must not appear in the catalog."""
    return _plant_listing(
        db_session,
        model_id="mcp_test_draft_001",
        name="mcp_test_draft",
        display_name="MCP Test Draft",
        description="A draft model that should NOT appear in catalog",
        category=ModelCategory.GENERAL.value,
        generator_type="generic",
        input_schema={},
        input_fields=[],
        example_input={},
        version="1.0.0",
        status="draft",
        is_official=False,
        is_public=True,
    )


@pytest.fixture
def private_catalog_model(db_session):
    """A published but private marketplace model — must not appear in the public catalog."""
    return _plant_listing(
        db_session,
        model_id="mcp_test_private_001",
        name="mcp_test_private",
        display_name="MCP Test Private",
        description="A private model that should NOT appear in public catalog",
        category=ModelCategory.GENERAL.value,
        generator_type="generic",
        input_schema={},
        input_fields=[],
        example_input={},
        version="1.0.0",
        status="published",
        is_official=False,
        is_public=False,
    )


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

    def test_list_templates_counts_the_whole_catalog_not_the_page(self, client):
        """``total`` describes everything that matched, so a client knows to page on."""
        response = client.get("/api/v2/solve/templates")
        data = response.json()

        assert data["total"] >= 100, f"Expected >= 100 templates, got {data['total']}"
        assert len(data["templates"]) <= data["page_size"]
        assert len(data["templates"]) < data["total"], (
            "the default page must not be the whole catalog — that was the 90 KB call"
        )

    # CONTRACT-TEST: paging must not lose or duplicate a template.
    def test_paging_walks_the_whole_catalog_exactly_once(self, client):
        """Every YAML template is reachable by paging, each exactly once."""
        first = client.get("/api/v2/solve/templates?page_size=25").json()
        total = first["total"]

        seen: list[str] = []
        page = 1
        while len(seen) < total:
            data = client.get(f"/api/v2/solve/templates?page={page}&page_size=25").json()
            if not data["templates"]:
                break
            seen.extend(t["id"] for t in data["templates"])
            page += 1

        assert len(seen) == total, f"paged {len(seen)} of {total}"
        assert len(set(seen)) == total, "a template appeared on two pages"
        yaml_only = {"nurse_scheduling", "demand_allocation", "store_layout", "budget_allocation"}
        assert yaml_only <= set(seen), f"missing after paging: {yaml_only - set(seen)}"

    def test_list_templates_contains_required_fields(self, client):
        """Each summary carries what a card needs — and not the long description.

        The long ``description`` was 59% of a 90 KB response (~22.6k tokens for an
        MCP client just looking at what exists) and ``get_template`` already
        serves it. Every template has a ``short_description``.
        """
        response = client.get("/api/v2/solve/templates?page_size=200")
        data = response.json()

        required_fields = {
            "id",
            "name",
            "display_name",
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
            assert "description" not in template, (
                f"Template {template['id']} still ships the long description in the listing"
            )
            assert template["short_description"].strip(), (
                f"Template {template['id']} has no short_description to show on its card"
            )

    def test_list_templates_tags_are_lists(self, client):
        """Template tags should be lists of strings."""
        response = client.get("/api/v2/solve/templates?page_size=200")
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
        """get_template falls back to a published marketplace listing when not in YAML."""
        response = client.get(f"/api/v2/solve/templates/{published_catalog_model.model_project_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == published_catalog_model.model_project_id
        assert data["display_name"] == published_catalog_model.display_name

    def test_get_template_db_fallback_draft_returns_404(
        self, client, db_session, draft_catalog_model
    ):
        """get_template DB fallback rejects draft (unpublished) models with 404."""
        response = client.get(f"/api/v2/solve/templates/{draft_catalog_model.model_project_id}")
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
        response = client.get(f"/api/v2/solve/templates/{published_catalog_model.model_project_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == published_catalog_model.model_project_id
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

    def test_validate_always_returns_errors_and_warnings_arrays(self, client):
        """Contract: /solve/validate ALWAYS returns `errors` and `warnings` arrays,
        for both the valid and invalid branches.

        The frontend `ValidationResult` type declares both as required `string[]` and
        the JSON-editor lens reads `validation.warnings.length` on every validated edit.
        Omitting `warnings` here crashed the whole studio page to the error boundary,
        which aborted the in-flight autosave (a variable just added was silently lost).
        """
        # Valid branch → both arrays present and empty.
        ok = client.post("/api/v2/solve/validate", json=VALID_PROBLEM)
        assert ok.status_code == 200
        ok_data = ok.json()
        assert ok_data["valid"] is True
        assert ok_data["errors"] == []
        assert ok_data["warnings"] == []

        # Invalid branch (schema-valid, but the objective names an undeclared variable)
        # → valid=False with a populated `errors` and still a (empty) `warnings` array.
        invalid = {
            "objective": {"sense": "minimize", "expression": "ghost"},
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
            "constraints": [],
        }
        bad = client.post("/api/v2/solve/validate", json=invalid)
        assert bad.status_code == 200
        bad_data = bad.json()
        assert bad_data["valid"] is False
        assert isinstance(bad_data["errors"], list) and len(bad_data["errors"]) > 0
        assert bad_data["warnings"] == []

    # CONTRACT-TEST: /solve/validate reports every structural error, not the first.
    def test_validate_reports_all_error_classes_at_once(self, client):
        """A problem broken in several ways lists every fault in one answer.

        It used to stop at the first raise, so an author fixing a hand-written
        model paid one round trip per mistake — and while they stared at the
        objective, nothing hinted the constraint and the bounds were wrong too.
        """
        broken = {
            "name": "broken",
            "objective": {"sense": "minimize", "expression": "ghost"},
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 5, "upper_bound": 1},
                {"name": "b", "type": "binary", "upper_bound": 7},
            ],
            "constraints": [{"name": "c1", "expression": "phantom + x <= 4"}],
        }
        response = client.post("/api/v2/solve/validate", json=broken)
        assert response.status_code == 200

        errors = response.json()["errors"]
        joined = " | ".join(errors)
        assert any("Objective" in e for e in errors), joined
        assert any("c1" in e for e in errors), joined
        assert any("invalid bounds" in e for e in errors), joined
        assert any("upper bound > 1" in e for e in errors), joined
        assert len(errors) >= 4, f"expected every fault, got {len(errors)}: {joined}"

    # CONTRACT-TEST: an expression validate approves must parse at solve time.
    def test_validate_rejects_syntactically_broken_expressions(self, client):
        """Measured against production (2026-08-02): these three expressions came
        back valid=True with zero errors, and the very same solve then failed.
        The validator's typical caller is an agent validating precisely to avoid
        buying a doomed solve, so approving what the solver will reject is the
        one failure mode this endpoint exists to prevent.
        """
        broken_expressions = [
            "x ++ 2 <= ",  # no right-hand side
            "x <= <= 3",  # doubled comparison operator
            "(x + 2 <= 3",  # unbalanced parenthesis
        ]
        for expression in broken_expressions:
            problem = {
                "name": "broken_syntax",
                "objective": {"sense": "maximize", "expression": "x"},
                "variables": [
                    {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 4}
                ],
                "constraints": [{"name": "c1", "expression": expression}],
            }
            response = client.post("/api/v2/solve/validate", json=problem)
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["valid"] is False, f"{expression!r} was approved and solve would fail"
            assert any("c1" in e for e in data["errors"]), data["errors"]

        # A broken objective is caught too, not just constraints.
        problem = {
            "name": "broken_objective",
            "objective": {"sense": "maximize", "expression": "x + * 2"},
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
            "constraints": [],
        }
        response = client.post("/api/v2/solve/validate", json=problem)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["valid"] is False
        assert any("Objective" in e for e in data["errors"]), data["errors"]

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
        assert published_catalog_model.model_project_id in model_ids

    def test_list_catalog_excludes_draft_models(self, client, db_session, draft_catalog_model):
        """list_catalog_models excludes unpublished (draft) models."""
        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        data = response.json()
        model_ids = [item["id"] for item in data["items"]]
        assert draft_catalog_model.model_project_id not in model_ids

    def test_list_catalog_excludes_private_models(self, client, db_session, private_catalog_model):
        """list_catalog_models excludes private (is_public=False) models."""
        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        data = response.json()
        model_ids = [item["id"] for item in data["items"]]
        assert private_catalog_model.model_project_id not in model_ids

    def test_list_catalog_model_has_required_fields(
        self, client, db_session, published_catalog_model
    ):
        """Each catalog model response contains expected fields."""
        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        data = response.json()
        test_model = next(
            (
                item
                for item in data["items"]
                if item["id"] == published_catalog_model.model_project_id
            ),
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
        response = client.get(f"/api/v2/models/catalog/{draft_catalog_model.model_project_id}")
        assert response.status_code == 404

    def test_get_catalog_model_schema_for_published(
        self, client, db_session, published_catalog_model
    ):
        """GET /models/catalog/{id}/schema returns schema data for published model."""
        response = client.get(
            f"/api/v2/models/catalog/{published_catalog_model.model_project_id}/schema"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == published_catalog_model.model_project_id
        assert "input_schema" in data
        assert "example_input" in data
        assert data["generator_type"] == "knapsack"
