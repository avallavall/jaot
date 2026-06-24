"""Tests for workspace role enforcement on solve and builder endpoints.

Verifies that:
  - POST /solve without workspace_id succeeds (org-level, no role check)
  - POST /solve?workspace_id=X as solver-role member succeeds
  - POST /solve?workspace_id=X as viewer-role member returns 403
  - POST /solve?workspace_id=X as non-member returns 403
  - POST /solve?workspace_id=X as org owner succeeds (owner bypass)
  - Builder endpoints enforce viewer/solver/editor roles via workspace_id
  - Without workspace_id, builder endpoints fall through to org-level access

Note: solve endpoint returns 402 when credits are insufficient — that means
the workspace role check PASSED (403 would indicate role enforcement).
For viewer tests we get 403 directly.
"""

import pytest

from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole
from app.models.workspace_credits import WorkspaceCreditPool
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _make_org(db, org_id, balance=500):
    org = Organization(
        id=org_id,
        name=f"Enforcement Org {org_id}",
        credits_balance=balance,
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
    pool = WorkspaceCreditPool(
        id=generate_id("wcp_"),
        workspace_id=ws.id,
        organization_id=org.id,
        allocated_credits=500,
        used_credits=0,
        created_at=now,
        updated_at=now,
    )
    db.add(pool)
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
        """POST /solve/templates/{id}/solve?workspace_id=X as solver passes role check.

        Template solve may legitimately return 200 or 402 (insufficient pool/org
        credits after dynamic credit calc) but must never return 403 or 5xx.
        """
        solver = enforcement_setup["solver"]
        ws = enforcement_setup["ws"]
        mock_auth(solver)
        resp = client.post(
            f"/api/v2/solve/templates/knapsack/solve?workspace_id={ws.id}",
            json={"capacity": 10, "items": [{"name": "a", "value": 5, "weight": 3}]},
        )
        assert resp.status_code in (200, 402), (
            f"Solver template solve expected 200 or 402, got {resp.status_code}: {resp.text}"
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


class TestWorkspacePoolConcurrency:
    """Workspace credit pool depletion under concurrent solves.

    Gap filled per audit missing-test #3 ("Workspace credit pool depletion
    under concurrency"). 20 concurrent deductions against one pool must
    each succeed atomically (no over-deduction, no lost updates).
    """

    def test_20_concurrent_pool_deducts_no_over_spend(self, db_session, db_engine):
        import queue
        import threading

        from sqlalchemy.orm import sessionmaker

        from app.models import Organization
        from app.models.workspace import Workspace
        from app.models.workspace_credits import WorkspaceCreditPool
        from app.services import workspace_credits_service

        # Seed an org + workspace + pool with exactly 20*50=1000 credits.
        org = _make_org(db_session, generate_id("org_"), balance=100_000)
        owner = _make_user(db_session, org, generate_id("usr_"), "poolowner@test.local")
        org.owner_user_id = owner.id
        now = utcnow()
        ws = Workspace(
            id=generate_id("wks_"),
            organization_id=org.id,
            name="Pool Concurrency WS",
            is_active=True,
            created_by=owner.id,
            created_at=now,
            updated_at=now,
        )
        db_session.add(ws)
        db_session.flush()
        pool = WorkspaceCreditPool(
            id=generate_id("wcp_"),
            workspace_id=ws.id,
            organization_id=org.id,
            allocated_credits=1000,
            used_credits=0,
            created_at=now,
            updated_at=now,
        )
        db_session.add(pool)
        db_session.commit()

        SessionFactory = sessionmaker(bind=db_engine)
        results: queue.Queue = queue.Queue()
        barrier = threading.Barrier(20, timeout=30)
        org_id = org.id
        ws_id = ws.id

        def worker(thread_id: int) -> None:
            session = SessionFactory()
            try:
                # Re-fetch the org inside this session.
                local_org = session.get(Organization, org_id)
                barrier.wait()
                source = workspace_credits_service.deduct_credits_for_solve(
                    db=session,
                    org=local_org,
                    workspace_id=ws_id,
                    credits_needed=50,
                )
                session.commit()
                results.put(("success", thread_id, source))
            except ValueError as exc:
                session.rollback()
                results.put(("insufficient", thread_id, str(exc)))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [threading.Thread(target=worker, args=(i,), name=f"pool-{i}") for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        alive = [t.name for t in threads if t.is_alive()]
        assert not alive, f"Threads still alive after 60s: {alive}"

        pool_successes = 0
        errors: list = []
        while not results.empty():
            r = results.get()
            if r[0] == "success" and r[2] == "pool":
                pool_successes += 1
            elif r[0] == "error":
                errors.append(r)

        assert not errors, f"Unexpected errors: {errors}"
        # All 20 must have hit the pool path and succeeded (pool=20*50=1000).
        assert pool_successes == 20, f"Expected 20 pool deductions, got {pool_successes}"

        # Pool must be fully used with no drift.
        fresh = SessionFactory()
        try:
            fresh_pool = (
                fresh.query(WorkspaceCreditPool).filter(WorkspaceCreditPool.id == pool.id).one()
            )
            assert fresh_pool.used_credits == 1000, (
                f"Pool used_credits drift: expected 1000, got {fresh_pool.used_credits}"
            )
            assert fresh_pool.allocated_credits == 1000
            # Org balance must NOT have been touched — pool fully absorbed the deductions.
            fresh_org = fresh.get(Organization, org_id)
            assert fresh_org.credits_balance == 100_000, (
                f"Org balance leak: expected 100000, got {fresh_org.credits_balance}"
            )
        finally:
            fresh.close()

    def test_concurrent_first_get_or_create_pool_no_duplicate(self, db_session, db_engine):
        """Concurrent first-GETs must not 500 on the unique(workspace_id) race.

        Phase 12 finding #13: _get_or_create_pool committed in a GET. Two
        concurrent first-GETs both find no pool and both INSERT; the loser's
        commit hits the unique(workspace_id) constraint. The handler now catches
        IntegrityError, rolls back, and re-fetches the winner's row, so
        get-or-create is idempotent: exactly ONE pool row, no uncaught error,
        and every caller returns that same id. (The invariant holds whether or
        not the race physically manifests — serialized runs also create once.)
        """
        import queue
        import threading

        from sqlalchemy.orm import sessionmaker

        from app.api.v2.routes.workspaces.credits import _get_or_create_pool
        from app.models.workspace import Workspace
        from app.models.workspace_credits import WorkspaceCreditPool

        # Workspace exists (FK satisfied) but has NO pool yet — force the race.
        org = _make_org(db_session, generate_id("org_"), balance=100_000)
        owner = _make_user(db_session, org, generate_id("usr_"), "getorcreate@test.local")
        org.owner_user_id = owner.id
        now = utcnow()
        ws = Workspace(
            id=generate_id("wks_"),
            organization_id=org.id,
            name="GetOrCreate Race WS",
            is_active=True,
            created_by=owner.id,
            created_at=now,
            updated_at=now,
        )
        db_session.add(ws)
        db_session.commit()
        org_id = org.id
        ws_id = ws.id

        SessionFactory = sessionmaker(bind=db_engine)
        results: queue.Queue = queue.Queue()
        n = 12
        barrier = threading.Barrier(n, timeout=30)

        def worker(thread_id: int) -> None:
            session = SessionFactory()
            try:
                barrier.wait()
                pool = _get_or_create_pool(session, ws_id, org_id)
                results.put(("ok", thread_id, pool.id))
            except Exception as exc:  # noqa: BLE001 — record, assert below
                session.rollback()
                results.put(("error", thread_id, repr(exc)))
            finally:
                session.close()

        threads = [threading.Thread(target=worker, args=(i,), name=f"goc-{i}") for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        alive = [t.name for t in threads if t.is_alive()]
        assert not alive, f"Threads still alive after 60s: {alive}"

        outcomes = []
        while not results.empty():
            outcomes.append(results.get())

        errors = [o for o in outcomes if o[0] == "error"]
        assert not errors, (
            f"_get_or_create_pool raised under concurrent first-create — the "
            f"unique(workspace_id) race is not handled (would surface as a 500): {errors}"
        )
        assert len(outcomes) == n, f"Expected {n} outcomes, got {len(outcomes)}"

        # Exactly ONE pool row, and every caller returned that single id.
        fresh = SessionFactory()
        try:
            rows = (
                fresh.query(WorkspaceCreditPool)
                .filter(WorkspaceCreditPool.workspace_id == ws_id)
                .all()
            )
            assert len(rows) == 1, (
                f"Expected exactly 1 pool row after the race, got {len(rows)}; "
                f"get-or-create is not idempotent under concurrency."
            )
            returned_ids = {o[2] for o in outcomes}
            assert returned_ids == {rows[0].id}, (
                f"All callers must return the single committed pool id "
                f"{rows[0].id}, got {returned_ids}"
            )
        finally:
            fresh.close()
