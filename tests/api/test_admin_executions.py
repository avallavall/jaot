"""# CONTRACT-TEST: the admin executions view spans every organization.

The panel's executions page called ``GET /models/executions/all``, which filters
by the caller's own organization. Under a heading reading "Monitor all model
executions across the platform" an admin saw one organization's runs and had no
way to tell: 1,176 of 1,234 rows on the development database, with 58 belonging
to three other organizations and simply absent.

Two more things that page could not do, and this endpoint must:

- name the organization each run belongs to (the column was empty on every row,
  because the response carried no organization at all)
- report a real average, computed over everything the filters select rather than
  over the twenty rows on screen — that sample said 6.15 s where the truth was
  763 ms
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ModelExecution, Organization, User
from app.models.model_project import ModelProject
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

pytestmark = pytest.mark.integration


def _execution(
    db: Session,
    *,
    org_id: str,
    time_ms: int,
    status: str = "completed",
    model_project_id: str | None = None,
    origin: str = "visual_builder",
) -> ModelExecution:
    row = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org_id,
        status=status,
        execution_time_ms=time_ms,
        origin=origin,
        model_project_id=model_project_id,
        # NOT NULL on the table. The endpoint defers this column rather than
        # reading it, which is the point of the list query.
        input_data={"name": "probe", "variables": [], "constraints": []},
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


class TestAdminExecutionsSpanThePlatform:
    def test_runs_of_every_organization_are_listed(
        self,
        admin_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_organization_2: Organization,
    ):
        mine = _execution(db_session, org_id=test_organization.id, time_ms=100)
        theirs = _execution(db_session, org_id=test_organization_2.id, time_ms=200)
        db_session.commit()

        resp = admin_client.get("/api/v2/admin/executions?page_size=100")

        assert resp.status_code == 200, resp.text
        ids = {row["id"] for row in resp.json()["items"]}
        assert mine.id in ids
        assert theirs.id in ids, "an execution of another organization is missing"

    def test_every_row_names_its_organization(
        self,
        admin_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
    ):
        theirs = _execution(db_session, org_id=test_organization_2.id, time_ms=200)
        db_session.commit()

        rows = admin_client.get("/api/v2/admin/executions?page_size=100").json()["items"]

        row = next(r for r in rows if r["id"] == theirs.id)
        assert row["organization_id"] == test_organization_2.id
        assert row["organization_name"] == test_organization_2.name

    def test_the_average_covers_the_whole_set_not_the_page(
        self,
        admin_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        """One slow run on page one must not become the platform's average.

        This is the shape of the original defect: the newest twenty rows held a
        few 20-second solves and the header reported 6.15 s for a platform whose
        real average was 763 ms.
        """
        for _ in range(4):
            _execution(db_session, org_id=test_organization.id, time_ms=100)
        _execution(db_session, org_id=test_organization.id, time_ms=20_000)
        db_session.commit()

        body = admin_client.get("/api/v2/admin/executions?page_size=2").json()

        assert len(body["items"]) == 2, "the page is still a page"
        assert body["stats"]["total"] >= 5
        # The average of everything, not of the two rows served.
        page_avg = sum(r["execution_time_ms"] or 0 for r in body["items"]) / 2
        assert body["stats"]["avg_execution_time_ms"] != pytest.approx(page_avg)

    def test_the_stats_follow_the_filters(
        self,
        admin_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        _execution(db_session, org_id=test_organization.id, time_ms=100, status="completed")
        _execution(db_session, org_id=test_organization.id, time_ms=900, status="failed")
        db_session.commit()

        everything = admin_client.get("/api/v2/admin/executions").json()["stats"]
        failed = admin_client.get("/api/v2/admin/executions?status=failed").json()["stats"]

        assert failed["total"] >= 1
        assert failed["total"] < everything["total"]

    def test_filtering_by_organization_narrows_to_it(
        self,
        admin_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_organization_2: Organization,
    ):
        _execution(db_session, org_id=test_organization.id, time_ms=100)
        _execution(db_session, org_id=test_organization_2.id, time_ms=200)
        db_session.commit()

        rows = admin_client.get(
            f"/api/v2/admin/executions?organization_id={test_organization_2.id}&page_size=100"
        ).json()["items"]

        assert rows
        assert {r["organization_id"] for r in rows} == {test_organization_2.id}

    def test_a_model_name_never_crosses_an_organization(
        self,
        admin_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """# CONTRACT-TEST: a run must not borrow another org's model name.

        ``source_id`` is client-supplied on the solve request. The org-scoped
        list is safe because it resolves names within one organization; this one
        spans organizations, so it matches on the pair and not on the id alone.
        """
        theirs = ModelProject(
            id=generate_id("mp_"),
            organization_id=test_organization_2.id,
            created_by=test_user_2.id,
            name="THEIR SECRET MODEL NAME",
            status="active",
        )
        db_session.add(theirs)
        db_session.flush()

        # A run in MY organization pointing at THEIR project id.
        impostor = _execution(
            db_session, org_id=test_organization.id, time_ms=10, model_project_id=theirs.id
        )
        db_session.commit()

        rows = admin_client.get("/api/v2/admin/executions?page_size=100").json()["items"]

        row = next(r for r in rows if r["id"] == impostor.id)
        assert row["model_name"] is None
        assert "THEIR SECRET MODEL NAME" not in resp_text(rows)

    def test_a_non_admin_is_refused(self, authenticated_client: TestClient):
        assert authenticated_client.get("/api/v2/admin/executions").status_code == 403


def resp_text(rows: list[dict]) -> str:
    import json

    return json.dumps(rows)
