"""Tests for the refactored seed_models script.

Tests upsert behavior, idempotency, deprecation of removed templates, and
JSON Schema generation from TemplateDefinition objects.
"""

from unittest.mock import patch

from app.data.templates._schema import TemplateDefinition
from app.models import ModelCatalog
from app.shared.db.seed_models import build_input_schema, seed_official_models


def _make_template(**overrides) -> TemplateDefinition:
    """Create a minimal valid TemplateDefinition for testing."""
    base = {
        "id": "test_tpl",
        "name": "Test Template",
        "display_name": "Test Template Display",
        "short_description": "Short desc",
        "description": "Full description of the template",
        "category": "finance",
        "generator_type": "generic",
        "input_schema": {"type": "object", "properties": {}},
        "input_fields": [
            {
                "name": "budget",
                "label": "Budget",
                "type": "number",
                "description": "The budget",
            }
        ],
        "example_input": {"budget": 1000},
    }
    base.update(overrides)
    return TemplateDefinition(**base)


class TestSeedOfficialModelsCreate:
    """Test that seed creates new ModelCatalog entries."""

    def test_creates_new_entries(self, db_session):
        tpl = _make_template(id="alpha")
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[tpl]):
            count = seed_official_models(db_session)

        assert count == 1
        entry = db_session.get(ModelCatalog, "official_alpha")
        assert entry is not None
        assert entry.name == "Test Template"
        assert entry.is_official is True
        assert entry.status == "published"

    def test_creates_multiple_entries(self, db_session):
        tpl1 = _make_template(id="one", name="One")
        tpl2 = _make_template(id="two", name="Two")
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[tpl1, tpl2]):
            count = seed_official_models(db_session)

        assert count == 2
        assert db_session.get(ModelCatalog, "official_one") is not None
        assert db_session.get(ModelCatalog, "official_two") is not None


class TestSeedOfficialModelsUpsert:
    """Test that re-running updates existing entries."""

    def test_updates_on_rerun(self, db_session):
        tpl_v1 = _make_template(id="upsert_test", name="Old Name")
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[tpl_v1]):
            seed_official_models(db_session)

        tpl_v2 = _make_template(id="upsert_test", name="New Name", description="Updated")
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[tpl_v2]):
            seed_official_models(db_session)

        entry = db_session.get(ModelCatalog, "official_upsert_test")
        assert entry.name == "New Name"
        assert entry.description == "Updated"


class TestSeedIdempotency:
    """Test no duplicates on re-run."""

    def test_no_duplicates(self, db_session):
        tpl = _make_template(id="idempotent")
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[tpl]):
            seed_official_models(db_session)
            seed_official_models(db_session)

        results = (
            db_session.query(ModelCatalog).filter(ModelCatalog.id == "official_idempotent").all()
        )
        assert len(results) == 1


class TestSeedDeprecation:
    """Test that removed templates get deprecated status."""

    def test_removed_template_deprecated(self, db_session):
        tpl1 = _make_template(id="keep_me")
        tpl2 = _make_template(id="remove_me")
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[tpl1, tpl2]):
            seed_official_models(db_session)

        # Second run without remove_me
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[tpl1]):
            seed_official_models(db_session)

        removed = db_session.get(ModelCatalog, "official_remove_me")
        assert removed is not None  # NOT deleted
        assert removed.status == "deprecated"

        kept = db_session.get(ModelCatalog, "official_keep_me")
        assert kept.status == "published"

    def test_deprecated_templates_not_deleted(self, db_session):
        tpl = _make_template(id="will_deprecate")
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[tpl]):
            seed_official_models(db_session)

        # Run twice with empty template list
        with patch("app.shared.db.seed_models.load_all_templates", return_value=[]):
            seed_official_models(db_session)
            seed_official_models(db_session)

        entry = db_session.get(ModelCatalog, "official_will_deprecate")
        assert entry is not None
        assert entry.status == "deprecated"


class TestSeedWarnings:
    """Test that unknown categories produce warnings."""

    def test_unknown_category_logged(self):
        """Verify that templates with unknown categories emit a warning.

        The warning is emitted by the Pydantic field_validator in _schema.py
        at TemplateDefinition construction time.

        Note: caplog doesn't work here because alembic.ini fileConfig resets
        loggers during the db_engine session fixture.
        """
        with patch("app.data.templates._schema.logger") as mock_logger:
            TemplateDefinition(
                id="bad_cat",
                name="Bad Category",
                display_name="Bad Category Display",
                short_description="Short",
                description="Full description",
                category="nonexistent_category",
                generator_type="generic",
                input_schema={"type": "object", "properties": {}},
                input_fields=[{"name": "x", "label": "X", "type": "number", "description": "val"}],
                example_input={"x": 1},
            )
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert "nonexistent_category" in str(call_args)


class TestBuildInputSchema:
    """Test JSON Schema generation from TemplateDefinition."""

    def test_produces_valid_json_schema(self):
        tpl = _make_template(
            input_fields=[
                {
                    "name": "budget",
                    "label": "Budget",
                    "type": "number",
                    "description": "The budget",
                    "required": True,
                    "minimum": 1,
                },
                {
                    "name": "name",
                    "label": "Name",
                    "type": "string",
                    "description": "Project name",
                    "required": False,
                },
            ]
        )
        schema = build_input_schema(tpl)
        assert schema["type"] == "object"
        assert "budget" in schema["properties"]
        assert schema["properties"]["budget"]["type"] == "number"
        assert schema["properties"]["budget"]["minimum"] == 1
        assert "budget" in schema["required"]
        assert "name" not in schema["required"]
