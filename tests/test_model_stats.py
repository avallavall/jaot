"""Tests for ModelStatsService + the shared classify() + Model Health Score (P1b).

Covers: stats correctness, the CONTRACT-TEST that ModelStatsService.problem_class
matches the auto-router's classification, the auditable health score (hard errors
cap at band F), the /projects/{id}/stats endpoint (org-scoped), and that
commit_version freezes stats_json + problem_class onto the immutable version.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domains.solver.services import ProblemClass, classify
from app.domains.solver.services.auto_router import (
    AUTO_REASON_FALLBACK,
    AUTO_REASON_LP,
    AUTO_REASON_MIP,
    AUTO_REASON_QUADRATIC,
    select_solver,
)
from app.models import Organization, User
from app.models.model_project import ModelProject, ModelProjectVersion
from app.schemas.optimization import OptimizationProblem
from app.services.model_stats_service import compute, compute_from_json
from tests._helpers.anti_oracle import assert_cross_tenant_404_anti_oracle


def _p(d: dict) -> OptimizationProblem:
    return OptimizationProblem.model_validate(d)


def _model(variables, objective, constraints) -> dict:
    return {"name": "t", "variables": variables, "objective": objective, "constraints": constraints}


# (label, model_json, expected_class, expected reason set for the router)
_CASES = [
    (
        "LP",
        _model(
            [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
            {"sense": "maximize", "expression": "x"},
            [{"name": "c", "expression": "x <= 5"}],
        ),
        ProblemClass.LP,
        {AUTO_REASON_LP},
    ),
    (
        "MILP",
        _model(
            [
                {"name": "x", "type": "continuous", "lower_bound": 0},
                {"name": "y", "type": "integer", "lower_bound": 0, "upper_bound": 5},
            ],
            {"sense": "maximize", "expression": "x + y"},
            [{"name": "c", "expression": "x + y <= 5"}],
        ),
        ProblemClass.MILP,
        {AUTO_REASON_MIP},
    ),
    (
        "IP",
        _model(
            [
                {"name": "x", "type": "integer", "lower_bound": 0, "upper_bound": 5},
                {"name": "y", "type": "integer", "lower_bound": 0, "upper_bound": 5},
            ],
            {"sense": "maximize", "expression": "x + y"},
            [{"name": "c", "expression": "x + y <= 5"}],
        ),
        ProblemClass.IP,
        {AUTO_REASON_MIP},
    ),
    (
        "BIP",
        _model(
            [{"name": "x", "type": "binary"}, {"name": "y", "type": "binary"}],
            {"sense": "maximize", "expression": "x + y"},
            [{"name": "c", "expression": "x + y <= 1"}],
        ),
        ProblemClass.BIP,
        {AUTO_REASON_MIP},
    ),
    (
        "QP",
        _model(
            [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
            {"sense": "minimize", "expression": "x*x"},
            [{"name": "c", "expression": "x >= 1"}],
        ),
        ProblemClass.QP,
        {AUTO_REASON_QUADRATIC, AUTO_REASON_FALLBACK},
    ),
    (
        "QCP",
        _model(
            [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
            {"sense": "minimize", "expression": "x"},
            [{"name": "c", "expression": "x*x <= 4"}],
        ),
        ProblemClass.QCP,
        {AUTO_REASON_QUADRATIC, AUTO_REASON_FALLBACK},
    ),
    (
        "MIQP",
        _model(
            [{"name": "x", "type": "integer", "lower_bound": 0, "upper_bound": 10}],
            {"sense": "minimize", "expression": "x*x"},
            [{"name": "c", "expression": "x >= 1"}],
        ),
        ProblemClass.MIQP,
        {AUTO_REASON_QUADRATIC, AUTO_REASON_FALLBACK},
    ),
]


class TestClassify:
    @pytest.mark.parametrize("label,model,expected,_reasons", _CASES, ids=[c[0] for c in _CASES])
    def test_classify_matches_expected(self, label, model, expected, _reasons):
        assert classify(_p(model)) == expected

    # CONTRACT-TEST: ModelStatsService.problem_class == auto_router classification
    @pytest.mark.parametrize("label,model,expected,reasons", _CASES, ids=[c[0] for c in _CASES])
    def test_stats_class_agrees_with_router(self, label, model, expected, reasons):
        problem = _p(model)
        assert compute(problem).problem_class == expected.value
        _solver, reason, _fallback = select_solver(problem)
        assert reason in reasons, f"{label}: router reason {reason} not in {reasons}"


class TestStatsCorrectness:
    def test_counts_and_density(self):
        stats = compute_from_json(_CASES[1][1])  # MILP: x continuous, y integer
        assert stats.var_total == 2
        assert stats.var_continuous == 1
        assert stats.var_integer == 1
        assert stats.constraint_total == 1
        assert stats.constraints_by_operator == {"<=": 1}
        assert stats.objective_sense == "maximize"
        assert stats.nonzeros == 2  # x + y in the one constraint
        assert 0 < stats.density <= 1
        assert stats.integrality_ratio == 0.5

    def test_bound_profile(self):
        stats = compute(
            _p(
                _model(
                    [
                        {"name": "a", "type": "continuous"},  # free
                        {
                            "name": "b",
                            "type": "continuous",
                            "lower_bound": 0,
                            "upper_bound": 1,
                        },  # boxed
                        {"name": "c", "type": "continuous", "lower_bound": 0},  # one-sided
                        {"name": "d", "type": "binary"},
                    ],
                    {"sense": "minimize", "expression": "a + b + c + d"},
                    [{"name": "k", "expression": "a + b + c + d >= 1"}],
                )
            )
        )
        assert stats.bound_profile.free == 1
        assert stats.bound_profile.boxed == 1
        assert stats.bound_profile.one_sided == 1
        assert stats.bound_profile.binary == 1


class TestHealth:
    def test_clean_model_scores_high(self):
        stats = compute_from_json(_CASES[0][1])  # tidy LP
        assert stats.health.has_hard_error is False
        assert stats.health.score >= 75
        assert stats.health.band in ("A", "B")

    def test_infeasible_bounds_is_hard_error_band_f(self):
        stats = compute(
            _p(
                _model(
                    [{"name": "x", "type": "continuous", "lower_bound": 5, "upper_bound": 1}],
                    {"sense": "minimize", "expression": "x"},
                    [{"name": "c", "expression": "x >= 0"}],
                )
            )
        )
        assert stats.health.has_hard_error is True
        assert stats.health.band == "F"
        assert stats.health.score <= 39
        assert any("lower_bound > upper_bound" in w for w in stats.warnings)

    def test_integer_missing_bounds_warns(self):
        stats = compute(
            _p(
                _model(
                    [{"name": "x", "type": "integer", "lower_bound": 0}],  # no upper bound
                    {"sense": "maximize", "expression": "x"},
                    [{"name": "c", "expression": "x <= 5"}],
                )
            )
        )
        assert stats.bound_profile.integers_missing_bounds == 1
        assert any("integer variable" in w for w in stats.warnings)

    def test_incomplete_model_does_not_raise(self):
        stats = compute_from_json({"variables": []})  # not a valid OptimizationProblem
        assert stats.problem_class is None
        assert any("incomplete" in w.lower() for w in stats.warnings)


class TestUnboundednessRisk:
    """# CONTRACT-TEST: the flag means "nothing stops this variable", not
    "this variable has no upper bound".

    Capping decision variables with capacity rows instead of with their own
    bounds is the ordinary way to write a model, so reading the flag off the
    bounds alone fired on almost everything — including models JAOT had just
    solved to a finite optimum — and docked 15 health points each time, live in
    the studio while the reader types.
    """

    _CAPPED_BY_ROWS = (
        [
            {"name": "x", "type": "continuous", "lower_bound": 0},
            {"name": "y", "type": "continuous", "lower_bound": 0},
        ],
        {"sense": "maximize", "expression": "3*x + 2*y"},
        [
            {"name": "c1", "expression": "x + y <= 4"},
            {"name": "c2", "expression": "x + 3*y <= 6"},
            {"name": "cap_x", "expression": "x <= 3"},
        ],
    )

    def test_rows_that_cap_a_variable_clear_the_flag(self):
        """Optimum 11 at (3,1) — finite, and JAOT solves it."""
        stats = compute(_p(_model(*self._CAPPED_BY_ROWS)))

        assert not any("UNBOUNDED" in w for w in stats.warnings), stats.warnings
        assert all(d.code != "unboundedness_risk" for d in stats.health.deductions)
        assert stats.health.band == "A"

    def test_a_variable_nothing_caps_is_still_flagged(self):
        """Precision, not silence: drop the rows that hold x down and it returns."""
        variables, objective, _ = self._CAPPED_BY_ROWS
        stats = compute(_p(_model(variables, objective, [{"name": "c2", "expression": "y <= 6"}])))

        assert any("UNBOUNDED" in w for w in stats.warnings), stats.warnings
        assert any(d.code == "unboundedness_risk" for d in stats.health.deductions)

    def test_a_row_capping_the_wrong_way_does_not_clear_it(self):
        """`x >= 1` bounds x from below; maximizing x is still unbounded above."""
        stats = compute(
            _p(
                _model(
                    [{"name": "x", "type": "continuous"}],
                    {"sense": "maximize", "expression": "x"},
                    [{"name": "floor", "expression": "x >= 1"}],
                )
            )
        )

        assert any("UNBOUNDED" in w for w in stats.warnings), stats.warnings

    def test_minimizing_reads_the_other_direction(self):
        """Minimizing a positive coefficient improves downward, so a floor caps it."""
        stats = compute(
            _p(
                _model(
                    [{"name": "x", "type": "continuous"}],
                    {"sense": "minimize", "expression": "x"},
                    [{"name": "floor", "expression": "x >= 1"}],
                )
            )
        )

        assert not any("UNBOUNDED" in w for w in stats.warnings), stats.warnings


class TestStatsEndpoint:
    def _create_with_draft(self, client: TestClient) -> str:
        pid = client.post("/api/v2/projects", json={"name": "S"}).json()["id"]
        resp = client.put(f"/api/v2/projects/{pid}/draft", json={"model_json": _CASES[0][1]})
        assert resp.status_code == 200, resp.text
        return pid

    def test_stats_endpoint_returns_class_and_health(self, authenticated_client: TestClient):
        pid = self._create_with_draft(authenticated_client)
        resp = authenticated_client.get(f"/api/v2/projects/{pid}/stats")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["problem_class"] == "LP"
        assert body["var_total"] == 1
        assert "health" in body and body["health"]["band"] in ("A", "B", "C", "D", "F")

    # CONTRACT-TEST: ModelProject endpoints filter organization_id (cross-org -> 404)
    def test_stats_cross_tenant_404(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        other = ModelProject(
            organization_id=test_organization_2.id,
            created_by=test_user_2.id,
            name="theirs",
            status="active",
        )
        db_session.add(other)
        db_session.commit()
        assert_cross_tenant_404_anti_oracle(
            authenticated_client,
            endpoint_template="/api/v2/projects/{id}/stats",
            cross_tenant_resource_id=other.id,
        )


class TestCommitFreezesStats:
    def test_commit_persists_stats_and_class(
        self, authenticated_client: TestClient, db_session: Session
    ):
        pid = authenticated_client.post("/api/v2/projects", json={"name": "C"}).json()["id"]
        authenticated_client.put(f"/api/v2/projects/{pid}/draft", json={"model_json": _CASES[0][1]})
        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "first version"}
        )
        assert resp.status_code in (200, 201), resp.text
        version = (
            db_session.query(ModelProjectVersion)
            .filter(ModelProjectVersion.model_project_id == pid)
            .one()
        )
        assert version.problem_class == "LP"
        assert version.stats_json is not None
        assert version.stats_json["health"]["band"] in ("A", "B", "C", "D", "F")
