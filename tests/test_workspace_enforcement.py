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
