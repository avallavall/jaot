"""Tests for the admin platform-analytics service + endpoints.

Service unit tests aggregate across all orgs; endpoint tests verify admin gating
(200 admin / 403 non-admin / 401 anon) and that empty data yields zeros, not 500.
"""

from datetime import timedelta
from decimal import Decimal

from app.models import (
    FormulationRating,
    LLMConversation,
    LLMMessage,
    ModelExecution,
    ModelProject,
    ModelProjectListing,
)
from app.services import platform_analytics_service as svc
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _exec(
    db,
    org_id,
    *,
    user_id=None,
    model_project_id=None,
    org_model_id=None,
    status="completed",
    solver_status="optimal",
    ms=100,
    origin="manual",
    is_async=False,
    created_at=None,
    started_at=None,
):
    exe = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org_id,
        executed_by_user_id=user_id,
        model_project_id=model_project_id,
        organization_model_id=org_model_id,
        input_data={},
        status=status,
        solver_status=solver_status,
        solver_name="scip",
        execution_time_ms=ms,
        origin=origin,
        is_async=is_async,
        created_at=created_at or utcnow(),
        started_at=started_at,
    )
    db.add(exe)
    db.flush()
    return exe


def _listed_project(db, org_id, category, *, success_rate=None, total_executions=0):
    """A ModelProject with a published marketplace listing (category lives there)."""
    project = ModelProject(
        id=generate_id("mp_"),
        organization_id=org_id,
        name=f"listed-{category}",
        status="active",
    )
    db.add(project)
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=project.id,
            name=project.name,
            display_name=f"Cat {category}",
            description="d",
            category=category,
            status="published",
            is_public=True,
            author_organization_id=org_id,
            success_rate=success_rate,
            total_executions=total_executions,
        )
    )
    db.flush()
    return project


def _fork_project(db, org_id, source_ref):
    """A fork ModelProject seeded from-marketplace (source_ref = the listing id)."""
    fork = ModelProject(
        id=generate_id("mp_"),
        organization_id=org_id,
        name="fork",
        status="active",
        source_type="marketplace",
        source_ref=source_ref,
    )
    db.add(fork)
    db.flush()
    return fork


def _conv(db, org_id, user_id, *, project_id=None, created_at=None):
    conv = LLMConversation(
        id=generate_id("conv_"),
        organization_id=org_id,
        user_id=user_id,
        model_project_id=project_id,  # None = not linked to a project ("not accepted")
        created_at=created_at or utcnow(),
        expires_at=utcnow() + timedelta(hours=24),
    )
    db.add(conv)
    db.flush()
    return conv


def _msg(db, conv_id, *, role="assistant", input_tokens=None, output_tokens=None, cost=None):
    msg = LLMMessage(
        id=generate_id("msg_"),
        conversation_id=conv_id,
        role=role,
        content="hi",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_eur=Decimal(str(cost)) if cost is not None else None,
    )
    db.add(msg)
    db.flush()
    return msg


def _rating(db, conv_id, user_id, org_id, rating):
    r = FormulationRating(
        id=generate_id("frt_"),
        conversation_id=conv_id,
        user_id=user_id,
        organization_id=org_id,
        rating=rating,
        zone="llm",
    )
    db.add(r)
    db.flush()
    return r


# ── Service: overview ───────────────────────────────────────────────────────
class TestOverviewService:
    def test_empty_is_zeroed(self, db_session):
        out = svc.compute_platform_overview(db_session, days=30)
        assert out["executions"]["total"] == 0
        assert out["executions"]["success_rate"] == 0.0
        assert out["by_category"] == []
        assert out["daily"] == []

    def test_users_and_orgs_counted(
        self, db_session, test_organization, test_user, test_admin_user
    ):
        out = svc.compute_platform_overview(db_session, days=30)
        # test_user + test_admin_user both belong to test_organization
        assert out["users"]["total"] >= 2
        assert out["orgs"]["total"] >= 1

    def test_execution_ratios(self, db_session, test_organization, test_user):
        for _ in range(4):
            _exec(db_session, test_organization.id, user_id=test_user.id)
        db_session.commit()
        out = svc.compute_platform_overview(db_session, days=30)
        assert out["executions"]["total"] == 4
        assert out["executions"]["per_org"] == 4.0  # 4 execs / 1 distinct org
        assert out["executions"]["per_user"] == 4.0  # 4 execs / 1 distinct user

    def test_success_rate(self, db_session, test_organization):
        _exec(db_session, test_organization.id, status="completed")
        _exec(db_session, test_organization.id, status="completed")
        _exec(db_session, test_organization.id, status="failed", solver_status="error")
        db_session.commit()
        out = svc.compute_platform_overview(db_session, days=30)
        assert out["executions"]["success_rate"] == 2 / 3

    def test_builder_solves(self, db_session, test_organization):
        listed = _listed_project(db_session, test_organization.id, "logistics")
        fork = _fork_project(db_session, test_organization.id, source_ref=listed.id)
        _exec(db_session, test_organization.id, model_project_id=fork.id)  # model run
        _exec(db_session, test_organization.id, status="completed")  # builder
        _exec(
            db_session,
            test_organization.id,
            status="failed",
            solver_status="error",
        )  # builder
        db_session.commit()
        out = svc.compute_platform_overview(db_session, days=30)
        assert out["builder_solves"]["total"] == 2  # only no-model executions
        assert out["builder_solves"]["success_rate"] == 0.5

    def test_by_category_join(self, db_session, test_organization):
        listed = _listed_project(db_session, test_organization.id, "logistics")
        fork = _fork_project(db_session, test_organization.id, source_ref=listed.id)
        # A fork resolves its category through its source listing…
        _exec(db_session, test_organization.id, model_project_id=fork.id, status="completed")
        _exec(
            db_session,
            test_organization.id,
            model_project_id=fork.id,
            status="failed",
            solver_status="error",
        )
        # …a listed project resolves its own listing directly…
        _exec(db_session, test_organization.id, model_project_id=listed.id, status="completed")
        # …and a model-less execution falls back to "custom".
        _exec(db_session, test_organization.id)
        db_session.commit()
        out = svc.compute_platform_overview(db_session, days=30)
        cats = {row["category"]: row for row in out["by_category"]}
        assert cats["logistics"]["executions"] == 3
        assert cats["logistics"]["success_rate"] == 2 / 3
        assert cats["custom"]["executions"] == 1

    def test_by_category_legacy_org_model_id(self, db_session, test_organization):
        """Historic executions carry only organization_model_id; the P1.5 backfill
        preserved that id as the project id, so the coalesce join resolves them.

        D-26 dropped the ``organization_models`` table but deliberately kept this
        column, precisely so these runs stay attributable — the shared id IS the
        link now, which is what this reproduces.
        """
        listed = _listed_project(db_session, test_organization.id, "finance")
        legacy_id = generate_id("omod_")
        db_session.add(
            ModelProject(
                id=legacy_id,
                organization_id=test_organization.id,
                name="backfilled fork",
                status="active",
                source_type="marketplace",
                source_ref=listed.id,
            )
        )
        db_session.flush()
        _exec(db_session, test_organization.id, org_model_id=legacy_id, status="completed")
        db_session.commit()
        out = svc.compute_platform_overview(db_session, days=30)
        cats = {row["category"]: row for row in out["by_category"]}
        assert cats["finance"]["executions"] == 1

    def test_days_window(self, db_session, test_organization):
        _exec(db_session, test_organization.id)
        _exec(db_session, test_organization.id, created_at=utcnow() - timedelta(days=60))
        db_session.commit()
        assert svc.compute_platform_overview(db_session, days=30)["executions"]["total"] == 1
        assert svc.compute_platform_overview(db_session, days=0)["executions"]["total"] == 2

    def test_cross_org_aggregation(self, db_session, test_organization, test_organization_2):
        _exec(db_session, test_organization.id)
        _exec(db_session, test_organization_2.id)
        db_session.commit()
        out = svc.compute_platform_overview(db_session, days=30)
        # platform-wide: BOTH orgs' executions counted (unlike org-scoped solver analytics)
        assert out["executions"]["total"] == 2
        assert out["executions"]["per_org"] == 1.0  # 2 execs / 2 distinct orgs


# ── Service: reliability ────────────────────────────────────────────────────
class TestReliabilityService:
    def test_empty_is_zeroed(self, db_session):
        out = svc.compute_reliability(db_session, days=30)
        assert out["total_executions"] == 0
        assert out["percentiles_ms"]["p50"] is None
        assert out["automation"]["total_triggers"] == 0

    def test_percentiles(self, db_session, test_organization):
        for ms in (100, 200, 300, 400):
            _exec(db_session, test_organization.id, ms=ms)
        db_session.commit()
        out = svc.compute_reliability(db_session, days=30)
        assert out["percentiles_ms"]["p50"] == 250.0  # percentile_cont of [100,200,300,400]

    def test_failure_and_timeout_rates(self, db_session, test_organization):
        _exec(db_session, test_organization.id, status="completed")
        _exec(db_session, test_organization.id, status="failed", solver_status="error")
        _exec(db_session, test_organization.id, status="timeout", solver_status=None)
        _exec(db_session, test_organization.id, status="completed")
        db_session.commit()
        out = svc.compute_reliability(db_session, days=30)
        assert out["failure_rate"] == 0.25
        assert out["timeout_rate"] == 0.25
        assert out["failures_by_solver_status"]["error"] == 1

    def test_async_split(self, db_session, test_organization):
        _exec(db_session, test_organization.id, is_async=True)
        _exec(db_session, test_organization.id, is_async=False)
        db_session.commit()
        out = svc.compute_reliability(db_session, days=30)
        assert out["async_count"] == 1
        assert out["sync_count"] == 1

    def test_queue_time(self, db_session, test_organization):
        now = utcnow()
        _exec(
            db_session, test_organization.id, created_at=now - timedelta(seconds=10), started_at=now
        )
        db_session.commit()
        out = svc.compute_reliability(db_session, days=30)
        assert out["avg_queue_time_s"] is not None
        assert 9.0 <= out["avg_queue_time_s"] <= 11.0

    def test_low_success_models(self, db_session, test_organization):
        project = _listed_project(
            db_session,
            test_organization.id,
            "finance",
            success_rate=0.4,
            total_executions=20,
        )
        db_session.commit()
        out = svc.compute_reliability(db_session, days=30)
        ids = {m["id"] for m in out["low_success_models"]}
        assert project.id in ids


# ── Service: AI usage ───────────────────────────────────────────────────────
class TestAiUsageService:
    def test_empty_is_zeroed(self, db_session):
        out = svc.compute_ai_usage(db_session, days=30)
        assert out["conversations"] == 0
        assert out["total_cost_eur"] == 0.0
        assert out["acceptance_rate"] == 0.0

    def test_tokens_cost_and_acceptance(self, db_session, test_organization, test_user):
        project = _listed_project(db_session, test_organization.id, "general")
        c1 = _conv(db_session, test_organization.id, test_user.id, project_id=project.id)
        _conv(db_session, test_organization.id, test_user.id)  # not accepted
        _msg(db_session, c1.id, input_tokens=100, output_tokens=50, cost=0.01)
        _msg(db_session, c1.id, input_tokens=200, output_tokens=80, cost=0.02)
        db_session.commit()
        out = svc.compute_ai_usage(db_session, days=30)
        assert out["conversations"] == 2
        assert out["messages"] == 2
        assert out["total_input_tokens"] == 300
        assert out["total_output_tokens"] == 130
        assert abs(out["total_cost_eur"] - 0.03) < 1e-6
        assert out["acceptance_rate"] == 0.5  # 1 of 2 conversations accepted
        assert out["orgs_using_ai"] == 1

    def test_thumbs(self, db_session, test_organization, test_user):
        c1 = _conv(db_session, test_organization.id, test_user.id)
        c2 = _conv(db_session, test_organization.id, test_user.id)
        c3 = _conv(db_session, test_organization.id, test_user.id)
        _rating(db_session, c1.id, test_user.id, test_organization.id, "up")
        _rating(db_session, c2.id, test_user.id, test_organization.id, "up")
        _rating(db_session, c3.id, test_user.id, test_organization.id, "down")
        db_session.commit()
        out = svc.compute_ai_usage(db_session, days=30)
        assert out["thumbs_up"] == 2
        assert out["thumbs_down"] == 1
        assert abs(out["thumbs_ratio"] - 2 / 3) < 1e-6


# ── Endpoints: admin gating + shape ─────────────────────────────────────────
_ENDPOINTS = (
    "/api/v2/admin/platform/overview",
    "/api/v2/admin/platform/reliability",
    "/api/v2/admin/platform/ai",
)


class TestPlatformAnalyticsEndpoints:
    def test_admin_ok(self, admin_client):
        for url in _ENDPOINTS:
            resp = admin_client.get(url)
            assert resp.status_code == 200, url
            assert resp.json()["days"] == 30

    # CONTRACT-TEST: platform analytics is admin-only
    def test_non_admin_forbidden(self, authenticated_client):
        for url in _ENDPOINTS:
            resp = authenticated_client.get(url)
            assert resp.status_code == 403, url

    def test_anonymous_unauthorized(self, client):
        for url in _ENDPOINTS:
            resp = client.get(url)
            assert resp.status_code == 401, url

    def test_overview_shape(self, admin_client):
        data = admin_client.get("/api/v2/admin/platform/overview").json()
        for key in (
            "users",
            "orgs",
            "avg_users_per_org",
            "executions",
            "by_category",
            "daily",
        ):
            assert key in data

    def test_days_param_validation(self, admin_client):
        assert admin_client.get("/api/v2/admin/platform/overview?days=500").status_code == 422
        assert admin_client.get("/api/v2/admin/platform/overview?days=0").status_code == 200
