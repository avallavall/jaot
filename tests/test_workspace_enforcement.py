"""Tests for workspace role enforcement on solve and builder endpoints.

Verifies that:
  - POST /solve without workspace_id succeeds (org-level, no role check)
  - POST /solve?workspace_id=X as solver-role member succeeds
  - POST /solve?workspace_id=X as viewer-role member returns 403
  - POST /solve?workspace_id=X as non-member returns 403
  - POST /solve?workspace_id=X as org owner succeeds (owner bypass)
  - Builder endpoints enforce viewer/solver/editor roles via workspace_id
  - Without workspace_id, builder endpoints fall through to org-level access

For viewer tests we get 403 directly.
"""

import pytest

from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _make_org(db, org_id, balance=500):
    org = Organization(
        id=org_id,
        name=f"Enforcement Org {org_id}",
        is_active=True,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_user(db, org, user_id, email, name="Member"):
    user = User(
        id=user_id,
        email=email,
        name=name,
        organization_id=org.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_workspace(db, org, owner):
    now = utcnow()
    ws = Workspace(
        id=generate_id("wks_"),
        organization_id=org.id,
        name="Enforcement WS",
        is_active=True,
        created_by=owner.id,
        created_at=now,
        updated_at=now,
    )
    db.add(ws)
    db.flush()
    db.commit()
    db.refresh(ws)
    return ws


def _add_member(db, ws, user, role):
    member = WorkspaceMember(
        id=generate_id("wkm_"),
        workspace_id=ws.id,
        user_id=user.id,
        organization_id=ws.organization_id,
        role=role,
        joined_at=utcnow(),
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


_SIMPLE_PROBLEM = {
    "name": "test_enforce",
    "objective": {"sense": "maximize", "expression": "x"},
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 1}],
    "constraints": [{"name": "c1", "expression": "x <= 1"}],
}


@pytest.fixture
def enforcement_setup(db_session, client):
    """Create org, owner, workspace, and role-specific members."""
    org = _make_org(db_session, "org_enf001", balance=1000)
    owner = _make_user(db_session, org, "usr_enfowner", "enfowner@example.com", "Owner")
    org.owner_user_id = owner.id
    db_session.commit()
    ws = _make_workspace(db_session, org, owner)

    solver = _make_user(db_session, org, "usr_enfsolver", "enfsolver@example.com", "Solver")
    editor = _make_user(db_session, org, "usr_enfeditor", "enfeditor@example.com", "Editor")
    viewer = _make_user(db_session, org, "usr_enfviewer", "enfviewer@example.com", "Viewer")
    non_member = _make_user(db_session, org, "usr_enfnomem", "enfnomem@example.com", "NoMember")

    _add_member(db_session, ws, solver, WorkspaceRole.SOLVER.value)
    _add_member(db_session, ws, editor, WorkspaceRole.EDITOR.value)
    _add_member(db_session, ws, viewer, WorkspaceRole.VIEWER.value)
    # owner has workspace admin access via owner_user_id bypass (no member row needed)

    return {
        "org": org,
        "ws": ws,
        "owner": owner,
        "solver": solver,
        "editor": editor,
        "viewer": viewer,
        "non_member": non_member,
    }


class TestSolveEnforcement:
    def test_solve_without_workspace_id_succeeds(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /solve without workspace_id succeeds: 200 for the 1-var problem.

        Org has 1000 credits and the minimal problem costs ~1 credit, so the
        solve should succeed outright. Any other status is a regression.
        """
        owner = enforcement_setup["owner"]
        mock_auth(owner)
        resp = client.post("/api/v2/solve", json=_SIMPLE_PROBLEM)
        assert resp.status_code == 200, (
            f"Expected 200 for owner solving a minimal problem, got {resp.status_code}: {resp.text}"
        )

    def test_solve_with_workspace_id_as_solver_succeeds(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /solve?workspace_id=X as solver-role returns 200 with pool+org credits.

        Workspace pool has 500 credits, org has 1000 credits, the problem costs ~1.
        Role check MUST pass AND the solve must actually succeed.
        """
        solver = enforcement_setup["solver"]
        ws = enforcement_setup["ws"]
        mock_auth(solver)
        resp = client.post(f"/api/v2/solve?workspace_id={ws.id}", json=_SIMPLE_PROBLEM)
        assert resp.status_code == 200, f"Solver expected 200, got {resp.status_code}: {resp.text}"

    def test_solve_with_workspace_id_as_viewer_returns_403(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /solve?workspace_id=X as viewer-role member returns 403."""
        viewer = enforcement_setup["viewer"]
        ws = enforcement_setup["ws"]
        mock_auth(viewer)
        resp = client.post(f"/api/v2/solve?workspace_id={ws.id}", json=_SIMPLE_PROBLEM)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_solve_with_workspace_id_as_non_member_returns_403(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /solve?workspace_id=X as non-member returns 403."""
        non_member = enforcement_setup["non_member"]
        ws = enforcement_setup["ws"]
        mock_auth(non_member)
        resp = client.post(f"/api/v2/solve?workspace_id={ws.id}", json=_SIMPLE_PROBLEM)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_solve_with_workspace_id_as_owner_succeeds(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /solve?workspace_id=X as org owner returns 200 (owner bypass)."""
        owner = enforcement_setup["owner"]
        ws = enforcement_setup["ws"]
        mock_auth(owner)
        resp = client.post(f"/api/v2/solve?workspace_id={ws.id}", json=_SIMPLE_PROBLEM)
        assert resp.status_code == 200, f"Owner expected 200, got {resp.status_code}: {resp.text}"


class TestBuilderEnforcement:
    def _make_doc(self, client, mock_auth, user):
        """Helper: create a builder document as the given user."""
        mock_auth(user)
        resp = client.post("/api/v2/builder/", json={"name": "Enforcement Doc"})
        assert resp.status_code == 201, f"Doc creation failed: {resp.text}"
        return resp.json()["id"]

    def test_create_doc_without_workspace_id_succeeds(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /builder/ without workspace_id succeeds (org-level)."""
        owner = enforcement_setup["owner"]
        mock_auth(owner)
        resp = client.post("/api/v2/builder/", json={"name": "Org Level Doc"})
        assert resp.status_code == 201, resp.text

    def test_create_doc_with_workspace_id_as_editor_succeeds(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /builder/?workspace_id=X as editor succeeds (editor >= solver)."""
        editor = enforcement_setup["editor"]
        ws = enforcement_setup["ws"]
        mock_auth(editor)
        resp = client.post(f"/api/v2/builder/?workspace_id={ws.id}", json={"name": "Editor Doc"})
        assert resp.status_code == 201, resp.text

    def test_create_doc_with_workspace_id_as_solver_succeeds(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /builder/?workspace_id=X as solver succeeds (solver can create models)."""
        solver = enforcement_setup["solver"]
        ws = enforcement_setup["ws"]
        mock_auth(solver)
        resp = client.post(f"/api/v2/builder/?workspace_id={ws.id}", json={"name": "Solver Doc"})
        assert resp.status_code == 201, resp.text

    def test_create_doc_with_workspace_id_as_viewer_returns_403(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /builder/?workspace_id=X as viewer returns 403."""
        viewer = enforcement_setup["viewer"]
        ws = enforcement_setup["ws"]
        mock_auth(viewer)
        resp = client.post(f"/api/v2/builder/?workspace_id={ws.id}", json={"name": "Viewer Doc"})
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_list_docs_with_workspace_id_as_viewer_succeeds(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """GET /builder/?workspace_id=X as viewer succeeds (viewer+ for reads)."""
        viewer = enforcement_setup["viewer"]
        ws = enforcement_setup["ws"]
        mock_auth(viewer)
        resp = client.get(f"/api/v2/builder/?workspace_id={ws.id}")
        assert resp.status_code == 200, resp.text

    def test_update_doc_with_workspace_id_as_editor_succeeds(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """PUT /builder/{id}?workspace_id=X as editor succeeds."""
        owner = enforcement_setup["owner"]
        ws = enforcement_setup["ws"]
        doc_id = self._make_doc(client, mock_auth, owner)

        editor = enforcement_setup["editor"]
        mock_auth(editor)
        resp = client.put(
            f"/api/v2/builder/{doc_id}?workspace_id={ws.id}",
            json={"name": "Updated by Editor"},
        )
        assert resp.status_code == 200, resp.text

    def test_update_doc_with_workspace_id_as_viewer_returns_403(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """PUT /builder/{id}?workspace_id=X as viewer returns 403."""
        owner = enforcement_setup["owner"]
        ws = enforcement_setup["ws"]
        doc_id = self._make_doc(client, mock_auth, owner)

        viewer = enforcement_setup["viewer"]
        mock_auth(viewer)
        resp = client.put(
            f"/api/v2/builder/{doc_id}?workspace_id={ws.id}",
            json={"name": "Hacked by Viewer"},
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_delete_doc_with_workspace_id_as_viewer_returns_403(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """DELETE /builder/{id}?workspace_id=X as viewer returns 403."""
        owner = enforcement_setup["owner"]
        ws = enforcement_setup["ws"]
        doc_id = self._make_doc(client, mock_auth, owner)

        viewer = enforcement_setup["viewer"]
        mock_auth(viewer)
        resp = client.delete(f"/api/v2/builder/{doc_id}?workspace_id={ws.id}")
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


class TestTemplateSolveEnforcement:
    def test_template_solve_with_workspace_as_solver_passes(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /solve/templates/{id}/solve?workspace_id=X as solver passes role check."""
        solver = enforcement_setup["solver"]
        ws = enforcement_setup["ws"]
        mock_auth(solver)
        resp = client.post(
            f"/api/v2/solve/templates/knapsack/solve?workspace_id={ws.id}",
            json={"capacity": 10, "items": [{"name": "a", "value": 5, "weight": 3}]},
        )
        assert resp.status_code == 200, (
            f"Solver template solve expected 200, got {resp.status_code}: {resp.text}"
        )

    def test_template_solve_with_workspace_as_viewer_returns_403(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """POST /solve/templates/{id}/solve?workspace_id=X as viewer returns 403."""
        viewer = enforcement_setup["viewer"]
        ws = enforcement_setup["ws"]
        mock_auth(viewer)
        resp = client.post(
            f"/api/v2/solve/templates/knapsack/solve?workspace_id={ws.id}",
            json={"capacity": 10, "items": [{"name": "a", "value": 5, "weight": 3}]},
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


class TestOrgOwnerBypass:
    def test_owner_can_solve_with_any_workspace_id(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """Org owner can solve in any workspace without explicit membership: 200."""
        owner = enforcement_setup["owner"]
        ws = enforcement_setup["ws"]
        mock_auth(owner)
        resp = client.post(f"/api/v2/solve?workspace_id={ws.id}", json=_SIMPLE_PROBLEM)
        assert resp.status_code == 200, f"Owner expected 200, got {resp.status_code}: {resp.text}"

    def test_owner_can_update_builder_docs_with_any_workspace_id(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """Org owner can update builder docs in any workspace."""
        owner = enforcement_setup["owner"]
        ws = enforcement_setup["ws"]

        mock_auth(owner)
        resp = client.post("/api/v2/builder/", json={"name": "Owner Doc"})
        assert resp.status_code == 201
        doc_id = resp.json()["id"]

        # Update with workspace_id
        resp = client.put(
            f"/api/v2/builder/{doc_id}?workspace_id={ws.id}",
            json={"name": "Owner Updated"},
        )
        assert resp.status_code == 200, f"Owner got {resp.status_code}: {resp.text}"


class TestTheRoleFollowsTheProjectNotTheQueryString:
    """The workspace a project is FILED IN decides, not the one the caller names.

    Found by driving the app (QA sweep, 2026-08-20). The ``OptionalRequire*``
    dependencies read ``workspace_id`` from the query string, and the caller owns
    the query string, so every workspace role was decorative for anybody in the
    organization:

        viewer -> PUT /projects/<id>/draft?workspace_id=<ws>  403 "need editor"
        viewer -> PUT /projects/<id>/draft                    200, draft written
        viewer -> DELETE /projects/<id>                       204, model archived
    """

    @staticmethod
    def _project_in(db, ws, org):
        from app.models.model_project import ModelProject

        project = ModelProject(
            id=generate_id("mp_"),
            organization_id=org.id,
            workspace_id=ws.id,
            name="Filed in a workspace",
            status="active",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    def test_a_viewer_cannot_write_the_draft_by_dropping_the_parameter(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        ws, org, viewer = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["viewer"],
        )
        project = self._project_in(db_session, ws, org)
        mock_auth(viewer)

        with_param = client.put(
            f"/api/v2/projects/{project.id}/draft?workspace_id={ws.id}",
            json={"dsl_source": "var x >= 0;\nmaximize x;\n"},
        )
        assert with_param.status_code == 403, with_param.text

        # The same call, one query parameter shorter.
        without = client.put(
            f"/api/v2/projects/{project.id}/draft",
            json={"dsl_source": "var x >= 0;\nmaximize x;\n"},
        )
        assert without.status_code == 403, without.text

        db_session.refresh(project)
        assert project.draft_dsl_source is None

    def test_a_viewer_cannot_archive_the_model_by_dropping_the_parameter(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        ws, org, viewer = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["viewer"],
        )
        project = self._project_in(db_session, ws, org)
        mock_auth(viewer)

        res = client.delete(f"/api/v2/projects/{project.id}")
        assert res.status_code == 403, res.text
        db_session.refresh(project)
        assert project.status == "active"

    def test_a_viewer_may_still_read_it(self, client, db_session, mock_auth, enforcement_setup):
        ws, org, viewer = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["viewer"],
        )
        project = self._project_in(db_session, ws, org)
        mock_auth(viewer)

        assert client.get(f"/api/v2/projects/{project.id}").status_code == 200

    def test_an_editor_writes_it_without_naming_the_workspace(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        ws, org, editor = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["editor"],
        )
        project = self._project_in(db_session, ws, org)
        mock_auth(editor)

        res = client.put(
            f"/api/v2/projects/{project.id}/draft",
            json={"dsl_source": "var x >= 0;\nmaximize x;\n"},
        )
        assert res.status_code == 200, res.text

    def test_somebody_who_is_in_no_workspace_at_all_is_refused(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        ws, org, outsider = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["non_member"],
        )
        project = self._project_in(db_session, ws, org)
        mock_auth(outsider)

        # Same organization, not in the workspace: the model is filed somewhere
        # they were never let into.
        assert client.get(f"/api/v2/projects/{project.id}").status_code == 403
        assert (
            client.put(
                f"/api/v2/projects/{project.id}/draft",
                json={"dsl_source": "var x >= 0;\nmaximize x;\n"},
            ).status_code
            == 403
        )

    def test_a_project_in_no_workspace_is_untouched(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        from app.models.model_project import ModelProject

        org, viewer = enforcement_setup["org"], enforcement_setup["viewer"]
        loose = ModelProject(
            id=generate_id("mp_"),
            organization_id=org.id,
            workspace_id=None,
            name="Org-level model",
            status="active",
        )
        db_session.add(loose)
        db_session.commit()
        mock_auth(viewer)

        # Org-level access, the way it worked before workspaces existed.
        res = client.put(
            f"/api/v2/projects/{loose.id}/draft",
            json={"dsl_source": "var x >= 0;\nmaximize x;\n"},
        )
        assert res.status_code == 200, res.text


class TestADatasetIsBehindTheSameWallAsItsProject:
    """# CONTRACT-TEST: reading one dataset by id obeys the workspace wall.

    Every other dataset route loads the project through ``_project_or_404`` or
    ``_writable_project_or_404``, which is what enforces the wall. The single-
    dataset GET only checked the organization, so somebody in the organization
    who is not in the workspace could read the full ``data_json`` of a scenario
    filed inside it. The list of datasets refused them; one direct id did not.
    """

    @staticmethod
    def _project_with_dataset(db, ws, org):
        from app.models.model_project import ModelProject, ModelProjectDataset

        project = ModelProject(
            id=generate_id("mp_"),
            organization_id=org.id,
            workspace_id=ws.id,
            name="Filed in a workspace",
            status="active",
        )
        db.add(project)
        db.flush()
        dataset = ModelProjectDataset(
            id=generate_id("mpd_"),
            model_project_id=project.id,
            organization_id=org.id,
            name="Q4 volumes",
            data_json={"demand": [120, 340, 90]},
        )
        db.add(dataset)
        db.commit()
        db.refresh(project)
        db.refresh(dataset)
        return project, dataset

    def test_a_non_member_cannot_read_a_dataset_by_its_id(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        ws, org, outsider = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["non_member"],
        )
        project, dataset = self._project_with_dataset(db_session, ws, org)
        mock_auth(outsider)

        listing = client.get(f"/api/v2/projects/{project.id}/datasets")
        assert listing.status_code == 403, listing.text

        # The same wall, reached by direct id instead of through the list.
        direct = client.get(f"/api/v2/projects/{project.id}/datasets/{dataset.id}")
        assert direct.status_code == 403, direct.text
        assert "demand" not in direct.text

    def test_a_viewer_of_the_workspace_still_reads_it(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """The wall must not shut out the people it is there to serve."""
        ws, org, viewer = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["viewer"],
        )
        project, dataset = self._project_with_dataset(db_session, ws, org)
        mock_auth(viewer)

        res = client.get(f"/api/v2/projects/{project.id}/datasets/{dataset.id}")
        assert res.status_code == 200, res.text
        assert res.json()["data_json"] == {"demand": [120, 340, 90]}


class TestARunIsBehindTheSameWallAsItsModel:
    """# CONTRACT-TEST: everything reached through a run's id obeys the workspace wall.

    Found by sweeping the wall route by route (QA, 2026-08-20). Every execution
    route filtered by ``organization_id`` and stopped there, so somebody in the
    organization who is not in the workspace could list a walled model's runs,
    open one, read its exact analysis and its insights, and export the whole
    problem — while the model itself answered 403 to the same caller. A version
    read by its id and a version diff had the same hole.
    """

    @staticmethod
    def _model_with_a_run(db, ws, org):
        from app.models.model_project import ModelProject, ModelProjectVersion
        from app.models.optimization_model import ExecutionStatus, ModelExecution

        problem = {
            "name": "walled",
            "variables": [{"name": "x", "type": "integer", "lower_bound": 0, "upper_bound": 4}],
            "objective": {"sense": "maximize", "expression": "3*x"},
            "constraints": [],
        }
        project = ModelProject(
            id=generate_id("mp_"),
            organization_id=org.id,
            workspace_id=ws.id,
            name="Filed in a workspace",
            status="active",
        )
        db.add(project)
        db.flush()
        version = ModelProjectVersion(
            id=generate_id("mpv_"),
            model_project_id=project.id,
            organization_id=org.id,
            sequence=1,
            commit_summary="v1",
            content_hash="hash_walled_run",
            model_json=problem,
        )
        execution = ModelExecution(
            id=generate_id("exe_"),
            organization_id=org.id,
            model_project_id=project.id,
            input_data=problem,
            result_data={"model": {"x": 4}, "objective_value": 12.0, "solver_status": "optimal"},
            status=ExecutionStatus.COMPLETED.value,
            solver_status="optimal",
            objective_value=12.0,
        )
        db.add_all([version, execution])
        db.commit()
        for row in (project, version, execution):
            db.refresh(row)
        return project, version, execution

    @staticmethod
    def _routes(project, version, execution):
        return [
            f"/api/v2/projects/{project.id}/versions/{version.id}",
            f"/api/v2/projects/{project.id}/versions/{version.id}/diff/{version.id}",
            f"/api/v2/models/{project.id}/executions",
            f"/api/v2/models/executions/{execution.id}",
            f"/api/v2/models/executions/{execution.id}/exact-analysis",
            f"/api/v2/solve/insights/{execution.id}",
            f"/api/v2/solve/export/{execution.id}/json",
        ]

    def test_a_non_member_reaches_none_of_them(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        ws, org, outsider = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["non_member"],
        )
        project, version, execution = self._model_with_a_run(db_session, ws, org)
        mock_auth(outsider)

        reached = [
            url
            for url in self._routes(project, version, execution)
            if client.get(url).status_code not in (403, 404)
        ]
        assert reached == [], f"these answered without asking the wall: {reached}"

    def test_a_viewer_of_the_workspace_reaches_all_of_them(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """The wall must not shut out the people it is there to serve."""
        ws, org, viewer = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["viewer"],
        )
        project, version, execution = self._model_with_a_run(db_session, ws, org)
        mock_auth(viewer)

        refused = [
            (url, res.status_code)
            for url in self._routes(project, version, execution)
            if (res := client.get(url)).status_code != 200
        ]
        assert refused == [], f"the wall shut a member out of: {refused}"

    def test_the_org_wide_history_hides_a_walled_run(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """An org-wide list cannot ask the wall per row, so it must filter up front."""
        ws, org, outsider, viewer = (
            enforcement_setup["ws"],
            enforcement_setup["org"],
            enforcement_setup["non_member"],
            enforcement_setup["viewer"],
        )
        _, _, execution = self._model_with_a_run(db_session, ws, org)
        url = "/api/v2/models/executions/all?page_size=100"

        mock_auth(outsider)
        outside = client.get(url)
        assert outside.status_code == 200, outside.text
        assert execution.id not in outside.text

        mock_auth(viewer)
        inside = client.get(url)
        assert inside.status_code == 200, inside.text
        assert execution.id in inside.text

    def test_a_run_that_belongs_to_no_model_stays_org_level(
        self, client, db_session, mock_auth, enforcement_setup
    ):
        """A one-off solve is filed in no workspace, so no wall applies to it."""
        from app.models.optimization_model import ExecutionStatus, ModelExecution

        org, outsider = enforcement_setup["org"], enforcement_setup["non_member"]
        loose = ModelExecution(
            id=generate_id("exe_"),
            organization_id=org.id,
            input_data={"name": "loose", "variables": [], "objective": {}, "constraints": []},
            result_data={"model": {}, "objective_value": 0.0, "solver_status": "optimal"},
            status=ExecutionStatus.COMPLETED.value,
            solver_status="optimal",
            objective_value=0.0,
        )
        db_session.add(loose)
        db_session.commit()
        mock_auth(outsider)

        res = client.get(f"/api/v2/models/executions/{loose.id}")
        assert res.status_code == 200, res.text
