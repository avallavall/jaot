"""Tests for the template quality scorecard service and admin endpoint.

Tests scoring logic with real YAML templates (no mocks).
"""

import pytest

from app.data.templates import load_all_templates
from app.services.template_scorecard import (
    CategoryScore,
    TemplateScore,
    run_scorecard,
    score_template,
)


class TestCategoryScore:
    def test_percentage_calculation(self):
        cs = CategoryScore(name="test", score=15, max_score=20)
        assert cs.percentage == 75.0

    def test_percentage_zero_max(self):
        cs = CategoryScore(name="test", score=0, max_score=0)
        assert cs.percentage == 0.0


class TestTemplateScore:
    def test_grade_boundaries(self):
        def _make(score: int) -> TemplateScore:
            return TemplateScore(
                template_id="t",
                template_name="T",
                category="c",
                generator_type="g",
                categories=(CategoryScore(name="all", score=score, max_score=100),),
            )

        assert _make(95).grade == "A"
        assert _make(90).grade == "A"
        assert _make(85).grade == "B"
        assert _make(80).grade == "B"
        assert _make(75).grade == "C"
        assert _make(70).grade == "C"
        assert _make(65).grade == "D"
        assert _make(60).grade == "D"
        assert _make(55).grade == "F"
        assert _make(0).grade == "F"

    def test_to_dict_has_required_keys(self):
        ts = TemplateScore(
            template_id="test_id",
            template_name="Test",
            category="general",
            generator_type="generic",
            categories=(CategoryScore(name="meta", score=10, max_score=20, notes=("note1",)),),
        )
        d = ts.to_dict()
        assert d["template_id"] == "test_id"
        assert d["total"] == 10
        assert d["max_total"] == 20
        assert d["grade"] == "F"
        assert len(d["categories"]) == 1
        assert d["categories"][0]["notes"] == ["note1"]


class TestScoreRealTemplates:
    """Score actual YAML templates and verify expected properties."""

    def test_all_templates_score_above_zero(self):
        templates = load_all_templates()
        assert len(templates) > 50, "Expected 50+ templates loaded"
        for t in templates:
            result = score_template(t)
            assert result.total > 0, f"{t.id} scored 0"

    def test_all_templates_have_5_categories(self):
        templates = load_all_templates()
        for t in templates[:10]:  # sample first 10
            result = score_template(t)
            assert len(result.categories) == 5, f"{t.id} has {len(result.categories)} categories"
            names = {c.name for c in result.categories}
            assert names == {
                "metadata",
                "input_schema",
                "example_input",
                "generator",
                "documentation",
            }

    def test_diet_optimization_uses_blending(self):
        """diet_optimization must use blending generator, not generic."""
        templates = load_all_templates()
        diet = next((t for t in templates if t.id == "diet_optimization"), None)
        assert diet is not None, "diet_optimization template not found"
        assert diet.generator_type == "blending"
        assert diet.category == "healthcare"

        result = score_template(diet)
        gen_cat = next(c for c in result.categories if c.name == "generator")
        # Should get full marks for using specialized generator
        assert gen_cat.score >= 13, f"diet generator score {gen_cat.score} too low"

    def test_specialized_generators_score_higher_than_generic(self):
        """Templates with specialized generators should outscore generic ones."""
        templates = load_all_templates()
        specialized = [score_template(t) for t in templates if t.generator_type != "generic"]
        generic = [score_template(t) for t in templates if t.generator_type == "generic"]

        if not generic:
            pytest.skip("No generic templates to compare")

        avg_specialized = sum(s.total for s in specialized) / len(specialized)
        avg_generic = sum(s.total for s in generic) / len(generic)
        assert avg_specialized > avg_generic, (
            f"Specialized avg ({avg_specialized:.1f}) should beat generic ({avg_generic:.1f})"
        )

    def test_no_template_scores_below_30(self):
        """All templates should meet minimum quality bar."""
        templates = load_all_templates()
        for t in templates:
            result = score_template(t)
            assert result.total >= 30, (
                f"{t.id} scored {result.total}/100 — below minimum quality threshold"
            )


class TestRunScorecard:
    def test_report_structure(self):
        report = run_scorecard()
        assert "total_templates" in report
        assert "average_score" in report
        assert "grade_distribution" in report
        assert "by_generator_type" in report
        assert "top_5" in report
        assert "bottom_5" in report
        assert "templates" in report
        assert report["total_templates"] > 50

    def test_report_sorted_descending(self):
        report = run_scorecard()
        scores = [t["total"] for t in report["templates"]]
        assert scores == sorted(scores, reverse=True)

    def test_grade_distribution_sums_to_total(self):
        report = run_scorecard()
        total_from_grades = sum(report["grade_distribution"].values())
        assert total_from_grades == report["total_templates"]


class TestScorecardEndpoint:
    def test_returns_200(self, admin_client):
        response = admin_client.get("/api/v2/admin/scorecard")
        assert response.status_code == 200
        data = response.json()
        assert "total_templates" in data
        assert "templates" in data
        # Non-empty real scorecard data
        assert data["total_templates"] > 0
        # When unfiltered, the templates list length must match total_templates
        assert len(data["templates"]) == data["total_templates"]

    def test_requires_admin(self, authenticated_client):
        response = authenticated_client.get("/api/v2/admin/scorecard")
        assert response.status_code == 403

    def test_unauthenticated_returns_401(self, client):
        response = client.get("/api/v2/admin/scorecard")
        assert response.status_code == 401

    def test_filter_by_grade(self, admin_client):
        response = admin_client.get("/api/v2/admin/scorecard?grade=F")
        assert response.status_code == 200
        data = response.json()
        for t in data["templates"]:
            assert t["grade"] == "F"

    def test_filter_by_min_score(self, admin_client):
        response = admin_client.get("/api/v2/admin/scorecard?min_score=70")
        assert response.status_code == 200
        data = response.json()
        for t in data["templates"]:
            assert t["total"] >= 70

    def test_filter_by_generator_type(self, admin_client):
        response = admin_client.get("/api/v2/admin/scorecard?generator_type=blending")
        assert response.status_code == 200
        data = response.json()
        for t in data["templates"]:
            assert t["generator_type"] == "blending"
        assert "filtered_count" in data
