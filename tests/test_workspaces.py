"""Comprehensive tests for workspace collaboration endpoints.

Covers:
  1. Workspace CRUD (6 tests)
  2. Member management (6 tests)
  3. Invite flows (8 tests)
  4. Permission enforcement (5 tests)
  5. Audit log (4 tests)
  6. Credit pool (6 tests)
"""

import hashlib
import secrets
from datetime import timedelta

import pytest

from app.models.audit_log import AuditAction, AuditLog
from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import (
    InviteMethod,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceRole,
)
from app.models.workspace_credits import WorkspaceCreditPool
from app.schemas.workspace import WorkspaceMemberResponse, WorkspaceResponse
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from tests._helpers.anti_oracle import (
    assert_cross_tenant_404_anti_oracle,
    assert_cross_tenant_404_anti_oracle_write,
)


def _make_org(db, org_id="org_ws001", balance=1000):
    org = Organization(
        id=org_id,
        name="WS Test Org",
        credits_balance=balance,
        is_active=True,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _make_user(db, org, user_id, email, name="Test Member"):
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


def _make_workspace(db, org, owner, name="Test WS"):
    """Create a workspace and add owner as admin member with credit pool."""
    now = utcnow()
    ws = Workspace(
        id=generate_id("wks_"),
        organization_id=org.id,
        name=name,
        is_active=True,
        created_by=owner.id,
        created_at=now,
        updated_at=now,
    )
    db.add(ws)
    db.flush()

    member = WorkspaceMember(
        id=generate_id("wkm_"),
        workspace_id=ws.id,
        user_id=owner.id,
        organization_id=org.id,
        role=WorkspaceRole.ADMIN.value,
        joined_at=now,
    )
    db.add(member)

    pool = WorkspaceCreditPool(
        id=generate_id("wcp_"),
        workspace_id=ws.id,
        organization_id=org.id,
        allocated_credits=0,
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


def _api_key_headers(client, db, app, user, org):
    """Set up request state mock so API calls are authenticated as user."""

    # We set the user directly via request.state through the test middleware.
    # The conftest mock_auth fixture does this more cleanly; here we set
    # app.state attributes via the context var approach used in conftest.
    # Simplest: just attach org to user and return Authorization header.
    user.organization = org
    return user


@pytest.fixture
def ws_setup(db_session, client):
    """Create org+owner+workspace for workspace tests."""
    org = _make_org(db_session)
    owner = _make_user(db_session, org, "usr_wsowner", "owner@ws.test", "WS Owner")
    org.owner_user_id = owner.id
    db_session.commit()
    ws = _make_workspace(db_session, org, owner)
    return {"org": org, "owner": owner, "ws": ws, "db": db_session}


@pytest.fixture
def ws_with_members(ws_setup, db_session):
    """Extend ws_setup with editor/solver/viewer members."""
    org = ws_setup["org"]
    ws = ws_setup["ws"]
    editor = _make_user(db_session, org, "usr_wseditor", "editor@ws.test", "WS Editor")
    solver = _make_user(db_session, org, "usr_wssolver", "solver@ws.test", "WS Solver")
    viewer = _make_user(db_session, org, "usr_wsviewer", "viewer@ws.test", "WS Viewer")
    _add_member(db_session, ws, editor, WorkspaceRole.EDITOR.value)
    _add_member(db_session, ws, solver, WorkspaceRole.SOLVER.value)
    _add_member(db_session, ws, viewer, WorkspaceRole.VIEWER.value)
    return {**ws_setup, "editor": editor, "solver": solver, "viewer": viewer}


@pytest.fixture
def cross_tenant_ws(db_session, client, mock_auth):
    """SC4 fixture: org_a + workspace owned by org_a; ALSO org_b user as caller.

    Layout:
      - org_a (the resource owner) + owner_a + workspace_a
      - org_b (the attacker) + user_b (attempts cross-tenant access)

    Both orgs include their respective owners so RequireAdmin /
    RequireViewer policies fire correctly when mock_auth(user_b) is set.

    Tests using this fixture then call assert_cross_tenant_404_anti_oracle(
    client, "/api/v2/workspaces/{id}", workspace_a.id) — the helper expects
    BOTH requests to 404 with byte-identical detail strings.
    """
    org_a = _make_org(db_session, "org_xt_a")
    owner_a = _make_user(db_session, org_a, "usr_xt_a", "owner-a@xt.test", "Owner A")
    org_a.owner_user_id = owner_a.id
    db_session.commit()
    ws_a = _make_workspace(db_session, org_a, owner_a, name="WS A")

    # Org B + a single owner-admin user. Owner of an org is implicitly admin
    # for any workspace in that org via the RequireAdmin dependency's
    # owner-shortcut path.
    org_b = _make_org(db_session, "org_xt_b")
    owner_b = _make_user(db_session, org_b, "usr_xt_b", "owner-b@xt.test", "Owner B")
    org_b.owner_user_id = owner_b.id
    db_session.commit()

    # Authenticate as org_b's owner — every helper call below issues
    # requests from org_b's tenancy.
    mock_auth(owner_b)

    return {
        "org_a": org_a,
        "owner_a": owner_a,
        "ws_a": ws_a,
        "org_b": org_b,
        "owner_b": owner_b,
    }


class TestWorkspaceCRUD:
    def test_create_workspace_as_owner(self, client, db_session, mock_auth):
        """Org owner can create a workspace."""
        org = _make_org(db_session, "org_crud01")
        owner = _make_user(db_session, org, "usr_crud01", "crud01@test.com", "CRUD Owner")
        org.owner_user_id = owner.id
        db_session.commit()

        mock_auth(owner)
        resp = client.post(
            "/api/v2/workspaces/",
            json={"name": "My Workspace", "description": "A test workspace"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["name"] == "My Workspace"
        assert data["description"] == "A test workspace"
        assert data["member_count"] == 1
        assert data["is_active"] is True

    def test_create_workspace_as_non_owner_fails(self, client, db_session, mock_auth):
        """Non-owner gets 403 when trying to create a workspace."""
        org = _make_org(db_session, "org_crud02")
        owner = _make_user(db_session, org, "usr_crud02o", "owner@crud02.test", "Owner")
        non_owner = _make_user(db_session, org, "usr_crud02n", "nonowner@crud02.test", "Non-Owner")
        org.owner_user_id = owner.id
        db_session.commit()

        mock_auth(non_owner)
        resp = client.post("/api/v2/workspaces/", json={"name": "Denied WS"})
        assert resp.status_code == 403

    def test_list_workspaces_member_filter(self, client, db_session, mock_auth, ws_with_members):
        """Member sees their own workspace but NEVER another org's workspace."""
        # Set up a totally separate org with its own workspace.
        other_org = _make_org(db_session, "org_other01")
        other_owner = _make_user(
            db_session, other_org, "usr_otherowner", "otherowner@ws.test", "Other Owner"
        )
        other_org.owner_user_id = other_owner.id
        db_session.commit()
        other_ws = _make_workspace(db_session, other_org, other_owner)

        viewer = ws_with_members["viewer"]
        mock_auth(viewer)
        resp = client.get("/api/v2/workspaces/")
        assert resp.status_code == 200
        data = resp.json()
        ids = [item["id"] for item in data["items"]]

        # Viewer sees their own workspace...
        assert ws_with_members["ws"].id in ids
        # ...but must NOT see the other org's workspace.
        assert other_ws.id not in ids, (
            "Cross-tenant leak: viewer from org A saw workspace from org B"
        )

    def test_get_workspace_detail(self, client, db_session, mock_auth, ws_setup):
        """Viewer can get workspace details."""
        org = ws_setup["org"]
        ws = ws_setup["ws"]
        viewer = _make_user(db_session, org, "usr_getws", "getws@test.com", "Viewer")
        _add_member(db_session, ws, viewer, WorkspaceRole.VIEWER.value)

        mock_auth(viewer)
        resp = client.get(f"/api/v2/workspaces/{ws.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == ws.id

    def test_update_workspace_as_admin(self, client, db_session, mock_auth, ws_setup):
        """Admin can update workspace name (T4: status + Pydantic + DB side-effect).

        TA-07: Strengthened from T3 status-only to T4 — asserts the response
        roundtrips through WorkspaceResponse (Pydantic v2) AND the persisted
        Workspace row in the DB has name='Renamed WS' after the PATCH.
        """
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        mock_auth(owner)
        resp = client.patch(f"/api/v2/workspaces/{ws.id}", json={"name": "Renamed WS"})

        # Tier-1: status
        assert resp.status_code == 200, resp.text

        # Tier-4: Pydantic schema roundtrip
        parsed = WorkspaceResponse.model_validate(resp.json())
        assert parsed.name == "Renamed WS"
        assert parsed.id == ws.id

        # Tier-4: DB side-effect
        db_session.expire_all()
        db_row = db_session.query(Workspace).filter(Workspace.id == ws.id).first()
        assert db_row is not None, "Workspace row missing after PATCH"
        assert db_row.name == "Renamed WS", (
            f"DB name not updated: expected 'Renamed WS', got {db_row.name!r}"
        )

    def test_update_workspace_name_too_long_returns_422(
        self, client, db_session, mock_auth, ws_setup
    ):
        """TA-07 edge: rename to a > 255 character name fails 422.

        The WorkspaceUpdate schema enforces name <= 255 (field validator). A
        regression where the validator was dropped would let admins write
        arbitrarily large names that break downstream UI rendering.
        """
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        mock_auth(owner)
        too_long = "X" * 256
        resp = client.patch(f"/api/v2/workspaces/{ws.id}", json={"name": too_long})
        assert resp.status_code == 422, resp.text

        # DB must NOT have been mutated
        db_session.expire_all()
        db_row = db_session.query(Workspace).filter(Workspace.id == ws.id).first()
        assert db_row is not None
        assert db_row.name != too_long, "Workspace name was mutated despite 422"

    def test_delete_workspace_as_owner(self, client, db_session, mock_auth, ws_setup):
        """Org owner can soft-delete a workspace."""
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        mock_auth(owner)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}")
        assert resp.status_code == 204

        db_session.refresh(ws)
        assert ws.is_active is False


class TestMemberManagement:
    def test_list_members(self, client, db_session, mock_auth, ws_with_members):
        """Viewer can list workspace members — exactly 4 with the expected roles."""
        viewer = ws_with_members["viewer"]
        ws = ws_with_members["ws"]

        mock_auth(viewer)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/members/")
        assert resp.status_code == 200
        data = resp.json()
        # owner + editor + solver + viewer = exactly 4
        assert len(data) == 4
        roles = sorted(member["role"] for member in data)
        assert roles == sorted(["admin", "editor", "solver", "viewer"]), (
            f"Expected [admin, editor, solver, viewer], got {roles}"
        )

    def test_update_role_as_admin_succeeds(self, client, db_session, mock_auth, ws_with_members):
        """Admin can change a member's role (T4: status + Pydantic + DB side-effect).

        TA-02: Strengthened from T3 status-only to T4 — asserts the response
        roundtrips through WorkspaceMemberResponse (Pydantic v2) AND the
        WorkspaceMember row in the DB has role='editor' after the PATCH.
        """
        owner = ws_with_members["owner"]
        solver = ws_with_members["solver"]
        ws = ws_with_members["ws"]

        mock_auth(owner)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{solver.id}",
            json={"role": "editor"},
        )

        # Tier-1: status
        assert resp.status_code == 200, resp.text

        # Tier-4: Pydantic schema roundtrip (validates response shape end-to-end)
        parsed = WorkspaceMemberResponse.model_validate(resp.json())
        assert parsed.role == "editor"
        assert parsed.user_id == solver.id

        # Tier-4: DB side-effect — the persisted row reflects the new role
        db_session.expire_all()
        db_row = (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == solver.id,
            )
            .first()
        )
        assert db_row is not None, "WorkspaceMember row missing after PATCH"
        assert db_row.role == "editor", (
            f"DB role not updated: expected 'editor', got {db_row.role!r}"
        )

    def test_update_role_to_owner_target_returns_400(
        self, client, db_session, mock_auth, ws_with_members
    ):
        """TA-02 edge: admin cannot change the org owner's workspace role (400).

        The members.py handler blocks role changes targeting the org owner
        because the owner's effective access is managed at the org level,
        not via a workspace_member.role field. Returning 200 here would
        allow an admin to demote the owner's workspace influence.
        """
        owner = ws_with_members["owner"]
        ws = ws_with_members["ws"]
        org = ws_with_members["org"]
        # Add a SECOND admin (not the org owner) so we can mock_auth them
        # and have them attempt to demote the owner — the per-handler check
        # in update_member_role refuses regardless of caller identity.
        second_admin = _make_user(
            db_session, org, "usr_ws2nd_admin", "second-admin@ws.test", "Second Admin"
        )
        _add_member(db_session, ws, second_admin, WorkspaceRole.ADMIN.value)

        mock_auth(second_admin)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{owner.id}",
            json={"role": "viewer"},
        )
        assert resp.status_code == 400, resp.text
        # The handler emits a specific detail mentioning the owner — any 400
        # is acceptable; we just confirm the forbidden-transition guard fires.
        assert "owner" in resp.json()["detail"].lower()

        # DB must NOT have been mutated
        db_session.expire_all()
        owner_member = (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == owner.id,
            )
            .first()
        )
        assert owner_member is not None
        assert owner_member.role == WorkspaceRole.ADMIN.value

    def test_update_role_as_editor_fails(self, client, db_session, mock_auth, ws_with_members):
        """Editor cannot change another member's role (needs admin)."""
        editor = ws_with_members["editor"]
        solver = ws_with_members["solver"]
        ws = ws_with_members["ws"]

        mock_auth(editor)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{solver.id}",
            json={"role": "viewer"},
        )
        assert resp.status_code == 403

    def test_remove_member_as_admin(self, client, db_session, mock_auth, ws_with_members):
        """Admin can remove a member."""
        owner = ws_with_members["owner"]
        viewer = ws_with_members["viewer"]
        ws = ws_with_members["ws"]

        mock_auth(owner)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/members/{viewer.id}")
        assert resp.status_code == 204

        # Verify removed
        member = (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == viewer.id,
            )
            .first()
        )
        assert member is None

    def test_cannot_remove_org_owner(self, client, db_session, mock_auth, ws_with_members):
        """Cannot remove the org owner from a workspace."""
        owner = ws_with_members["owner"]
        ws = ws_with_members["ws"]

        mock_auth(owner)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/members/{owner.id}")
        # owner is trying to remove themselves — caught by "cannot remove yourself" check
        assert resp.status_code == 400

    def test_cannot_change_own_role(self, client, db_session, mock_auth, ws_with_members):
        """Admin cannot change their own role."""
        owner = ws_with_members["owner"]
        ws = ws_with_members["ws"]

        mock_auth(owner)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{owner.id}",
            json={"role": "viewer"},
        )
        assert resp.status_code == 400


class TestInviteFlows:
    def _hash(self, token):
        return hashlib.sha256(token.encode()).hexdigest()

    def test_create_email_invite(self, client, db_session, mock_auth, ws_setup):
        """Admin can create an email invite."""
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        mock_auth(owner)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "new@example.com", "role": "editor"},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["method"] == "email"
        assert data["role"] == "editor"
        assert data["invitee_email"] == "new@example.com"

    def test_create_link_invite_returns_url(self, client, db_session, mock_auth, ws_setup):
        """Admin can create a link invite that returns an invite_url."""
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        mock_auth(owner)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/link",
            json={"role": "solver"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "invite_url" in data
        assert data["invite_url"].startswith("/join/")

    def test_accept_email_invite_creates_member(self, client, db_session, mock_auth, ws_setup):
        """Accepting an email invite creates a workspace member with correct role."""
        org = ws_setup["org"]
        ws = ws_setup["ws"]

        acceptor = _make_user(db_session, org, "usr_acceptor1", "accept1@test.com", "Acceptor")

        # Create invite directly in DB
        plaintext = secrets.token_urlsafe(32)
        token_hash = self._hash(plaintext)
        invite = WorkspaceInvite(
            id=generate_id("inv_"),
            workspace_id=ws.id,
            organization_id=org.id,
            role="editor",
            method=InviteMethod.EMAIL.value,
            invitee_email="accept1@test.com",
            token_hash=token_hash,
            created_by=ws_setup["owner"].id,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(days=7),
            is_revoked=False,
        )
        db_session.add(invite)
        db_session.commit()

        mock_auth(acceptor)
        resp = client.post("/api/v2/workspaces/invites/accept", json={"token": plaintext})
        assert resp.status_code == 200
        assert "Successfully joined" in resp.json()["message"]

        # Verify member row created
        member = (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == acceptor.id,
            )
            .first()
        )
        assert member is not None
        assert member.role == "editor"

    def test_accept_expired_invite_fails(self, client, db_session, mock_auth, ws_setup):
        """Accepting an expired invite returns 400."""
        org = ws_setup["org"]
        ws = ws_setup["ws"]
        acceptor = _make_user(db_session, org, "usr_expiry1", "expiry1@test.com", "Expiry User")

        plaintext = secrets.token_urlsafe(32)
        token_hash = self._hash(plaintext)
        invite = WorkspaceInvite(
            id=generate_id("inv_"),
            workspace_id=ws.id,
            organization_id=org.id,
            role="viewer",
            method=InviteMethod.EMAIL.value,
            invitee_email="expiry1@test.com",
            token_hash=token_hash,
            created_by=ws_setup["owner"].id,
            created_at=utcnow() - timedelta(days=10),
            expires_at=utcnow() - timedelta(days=3),  # expired
            is_revoked=False,
        )
        db_session.add(invite)
        db_session.commit()

        mock_auth(acceptor)
        resp = client.post("/api/v2/workspaces/invites/accept", json={"token": plaintext})
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_accept_revoked_invite_fails(self, client, db_session, mock_auth, ws_setup):
        """Accepting a revoked invite returns 400."""
        org = ws_setup["org"]
        ws = ws_setup["ws"]
        acceptor = _make_user(db_session, org, "usr_revoked1", "revoked1@test.com", "Revoked User")

        plaintext = secrets.token_urlsafe(32)
        token_hash = self._hash(plaintext)
        invite = WorkspaceInvite(
            id=generate_id("inv_"),
            workspace_id=ws.id,
            organization_id=org.id,
            role="viewer",
            method=InviteMethod.EMAIL.value,
            invitee_email="revoked1@test.com",
            token_hash=token_hash,
            created_by=ws_setup["owner"].id,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(days=7),
            is_revoked=True,  # revoked
        )
        db_session.add(invite)
        db_session.commit()

        mock_auth(acceptor)
        resp = client.post("/api/v2/workspaces/invites/accept", json={"token": plaintext})
        assert resp.status_code == 400
        assert "revoked" in resp.json()["detail"].lower()

    def test_link_invite_idempotent(self, client, db_session, mock_auth, ws_setup):
        """Second accept of a link invite by the same user returns 200 (not duplicate)."""
        org = ws_setup["org"]
        ws = ws_setup["ws"]
        acceptor = _make_user(db_session, org, "usr_idem1", "idem1@test.com", "Idempotent")

        plaintext = secrets.token_urlsafe(32)
        token_hash = self._hash(plaintext)
        invite = WorkspaceInvite(
            id=generate_id("inv_"),
            workspace_id=ws.id,
            organization_id=org.id,
            role="solver",
            method=InviteMethod.LINK.value,
            invitee_email=None,
            token_hash=token_hash,
            created_by=ws_setup["owner"].id,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(days=7),
            is_revoked=False,
        )
        db_session.add(invite)
        db_session.commit()

        mock_auth(acceptor)
        resp1 = client.post("/api/v2/workspaces/invites/accept", json={"token": plaintext})
        assert resp1.status_code == 200

        # Second call — idempotent
        resp2 = client.post("/api/v2/workspaces/invites/accept", json={"token": plaintext})
        assert resp2.status_code == 200
        assert "already a member" in resp2.json()["message"].lower()

    def test_list_pending_invites(self, client, db_session, mock_auth, ws_setup):
        """Admin sees exactly one pending invite with the seeded email and role."""
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]
        org = ws_setup["org"]

        # Add an invite
        token_hash = self._hash(secrets.token_urlsafe(32))
        invite = WorkspaceInvite(
            id=generate_id("inv_"),
            workspace_id=ws.id,
            organization_id=org.id,
            role="viewer",
            method=InviteMethod.EMAIL.value,
            invitee_email="list@test.com",
            token_hash=token_hash,
            created_by=owner.id,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(days=7),
            is_revoked=False,
        )
        db_session.add(invite)
        db_session.commit()

        mock_auth(owner)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/invites/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        row = data[0]
        assert row["invitee_email"] == "list@test.com"
        assert row["role"] == "viewer"
        assert row["is_revoked"] is False

    def test_revoke_invite(self, client, db_session, mock_auth, ws_setup):
        """Admin can revoke an invite."""
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]
        org = ws_setup["org"]

        token_hash = self._hash(secrets.token_urlsafe(32))
        invite = WorkspaceInvite(
            id=generate_id("inv_"),
            workspace_id=ws.id,
            organization_id=org.id,
            role="viewer",
            method=InviteMethod.EMAIL.value,
            invitee_email="revoke@test.com",
            token_hash=token_hash,
            created_by=owner.id,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(days=7),
            is_revoked=False,
        )
        db_session.add(invite)
        db_session.commit()

        mock_auth(owner)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/invites/{invite.id}")
        assert resp.status_code == 204

        db_session.refresh(invite)
        assert invite.is_revoked is True


class TestPermissionEnforcement:
    def test_viewer_cannot_edit_workspace(self, client, db_session, mock_auth, ws_with_members):
        """Viewer cannot update workspace (403)."""
        viewer = ws_with_members["viewer"]
        ws = ws_with_members["ws"]

        mock_auth(viewer)
        resp = client.patch(f"/api/v2/workspaces/{ws.id}", json={"name": "Hacked"})
        assert resp.status_code == 403

    def test_solver_cannot_manage_members(self, client, db_session, mock_auth, ws_with_members):
        """Solver cannot update member roles (403)."""
        solver = ws_with_members["solver"]
        viewer = ws_with_members["viewer"]
        ws = ws_with_members["ws"]

        mock_auth(solver)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{viewer.id}",
            json={"role": "solver"},
        )
        assert resp.status_code == 403

    def test_editor_cannot_allocate_credits(self, client, db_session, mock_auth, ws_with_members):
        """Editor cannot allocate credits to workspace pool (403)."""
        editor = ws_with_members["editor"]
        ws = ws_with_members["ws"]

        mock_auth(editor)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/credits/allocate",
            json={"amount": 100},
        )
        assert resp.status_code == 403

    def test_admin_can_do_all_workspace_operations(self, client, db_session, mock_auth, ws_setup):
        """Admin (org owner) can: update, list members, allocate credits, add member.

        Previously this test only checked two endpoints despite claiming "all
        operations". Now it covers update + list-members + credit-allocation
        + member-management + audit-log read, which is the full admin surface.
        """
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]
        org = ws_setup["org"]
        # Seed the org with enough credits for the allocation test.
        org.credits_balance = 1000
        db_session.commit()

        mock_auth(owner)

        # 1. Update workspace
        resp = client.patch(f"/api/v2/workspaces/{ws.id}", json={"name": "Admin Updated"})
        assert resp.status_code == 200

        # 2. List members
        resp = client.get(f"/api/v2/workspaces/{ws.id}/members/")
        assert resp.status_code == 200

        # 3. Allocate credits to the workspace pool
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/credits/allocate",
            json={"amount": 100},
        )
        assert resp.status_code == 200, f"Credit allocation failed: {resp.text}"

        # 4. Access the audit log (admin-only endpoint)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/audit/")
        assert resp.status_code == 200

        # 5. Add a new member via email invite (member management surface)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "new-member@admin-test.example", "role": "viewer"},
        )
        assert resp.status_code == 201, f"Member invite failed: {resp.text}"

    def test_non_admin_cannot_access_audit(self, client, db_session, mock_auth, ws_with_members):
        """Viewer cannot access audit log (403)."""
        viewer = ws_with_members["viewer"]
        ws = ws_with_members["ws"]

        mock_auth(viewer)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/audit/")
        assert resp.status_code == 403


class TestAuditLog:
    def test_audit_log_records_workspace_creation(self, client, db_session, mock_auth):
        """Creating a workspace creates an audit log entry."""
        org = _make_org(db_session, "org_audit01")
        owner = _make_user(db_session, org, "usr_audit01", "audit01@test.com", "Audit Owner")
        org.owner_user_id = owner.id
        db_session.commit()

        mock_auth(owner)
        resp = client.post("/api/v2/workspaces/", json={"name": "Audit WS"})
        assert resp.status_code == 201
        ws_id = resp.json()["id"]

        logs = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.organization_id == org.id,
                AuditLog.workspace_id == ws_id,
                AuditLog.action == AuditAction.WORKSPACE_CREATE.value,
            )
            .all()
        )
        assert len(logs) == 1

    def test_audit_log_records_member_invite(self, client, db_session, mock_auth, ws_setup):
        """Creating an email invite creates an audit log entry."""
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]
        org = ws_setup["org"]

        mock_auth(owner)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "invitee@example.com", "role": "viewer"},
        )
        assert resp.status_code == 201

        logs = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.organization_id == org.id,
                AuditLog.workspace_id == ws.id,
                AuditLog.action == AuditAction.MEMBER_INVITE.value,
            )
            .all()
        )
        assert len(logs) >= 1

    def test_audit_log_filter_by_action(self, client, db_session, mock_auth, ws_setup):
        """Audit log filter by action type returns matching rows and only those rows."""
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        mock_auth(owner)
        client.patch(f"/api/v2/workspaces/{ws.id}", json={"name": "Filtered WS"})

        resp = client.get(f"/api/v2/workspaces/{ws.id}/audit/?action=workspace_update")
        assert resp.status_code == 200
        data = resp.json()
        # Must actually have rows to iterate over, else the loop below is vacuous.
        assert len(data["items"]) >= 1, "Expected at least one workspace_update audit log entry"
        for item in data["items"]:
            assert item["action"] == "workspace_update"


class TestCreditPool:
    def test_get_pool_stats(self, client, db_session, mock_auth, ws_with_members):
        """Viewer can get pool stats."""
        viewer = ws_with_members["viewer"]
        ws = ws_with_members["ws"]

        mock_auth(viewer)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/credits/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workspace_id"] == ws.id
        assert data["allocated_credits"] == 0
        assert data["available_credits"] == 0

    def test_allocate_credits_deducts_from_org_balance(
        self, client, db_session, mock_auth, ws_setup
    ):
        """Allocating credits reduces org balance and increases pool."""
        owner = ws_setup["owner"]
        org = ws_setup["org"]
        ws = ws_setup["ws"]
        initial_balance = org.credits_balance

        mock_auth(owner)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/credits/allocate",
            json={"amount": 200},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["allocated_credits"] == 200
        assert data["available_credits"] == 200

        db_session.refresh(org)
        assert org.credits_balance == initial_balance - 200

    def test_allocate_more_than_balance_fails(self, client, db_session, mock_auth, ws_setup):
        """Allocating more credits than org balance fails with 400."""
        owner = ws_setup["owner"]
        org = ws_setup["org"]
        ws = ws_setup["ws"]

        mock_auth(owner)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/credits/allocate",
            json={"amount": org.credits_balance + 9999},
        )
        assert resp.status_code == 400

    def test_pool_stats_reflect_allocation(self, client, db_session, mock_auth, ws_setup):
        """Pool stats show correct values after allocation."""
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        mock_auth(owner)
        client.post(
            f"/api/v2/workspaces/{ws.id}/credits/allocate",
            json={"amount": 100},
        )

        resp = client.get(f"/api/v2/workspaces/{ws.id}/credits/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["allocated_credits"] == 100
        assert data["used_credits"] == 0
        assert data["available_credits"] == 100

    def test_view_pool_as_viewer_succeeds(self, client, db_session, mock_auth, ws_with_members):
        """Viewer can read pool stats (viewer+ permission)."""
        viewer = ws_with_members["viewer"]
        ws = ws_with_members["ws"]

        mock_auth(viewer)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/credits/")
        assert resp.status_code == 200

    def test_allocate_as_non_admin_fails(self, client, db_session, mock_auth, ws_with_members):
        """Editor cannot allocate credits (requires admin)."""
        editor = ws_with_members["editor"]
        ws = ws_with_members["ws"]

        mock_auth(editor)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/credits/allocate",
            json={"amount": 50},
        )
        assert resp.status_code == 403

    def test_get_pool_on_soft_deleted_workspace_succeeds(
        self, client, db_session, mock_auth, ws_setup
    ):
        """GET pool stays viewable on a soft-deleted workspace (reconciliation).

        Phase 12 finding #11: the IDOR fix bundled is_active into
        get_workspace_or_404, which 404'd the read-only pool GET on soft-deleted
        workspaces. But delete_workspace does NOT reclaim allocated pool credits,
        so they would be both stranded AND invisible. The GET now passes
        require_active=False so the owning org can still see (reconcile) the
        pool; org_id is still enforced.
        """
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        # Fund the pool, then soft-delete the workspace -> 150 credits stranded.
        mock_auth(owner)
        alloc = client.post(f"/api/v2/workspaces/{ws.id}/credits/allocate", json={"amount": 150})
        assert alloc.status_code == 200, alloc.text[:200]
        ws.is_active = False
        db_session.commit()

        # GET still returns the pool with the stranded credits visible.
        resp = client.get(f"/api/v2/workspaces/{ws.id}/credits/")
        assert resp.status_code == 200, (
            f"Soft-deleted workspace pool GET should stay viewable, got "
            f"{resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert data["workspace_id"] == ws.id
        assert data["allocated_credits"] == 150  # stranded, still visible

    def test_allocate_to_soft_deleted_workspace_fails_404(
        self, client, db_session, mock_auth, ws_setup
    ):
        """Allocation stays STRICT on soft-deleted workspaces (require_active=True).

        Phase 12 finding #11: only the read-only GET was relaxed. Funding a
        deleted workspace must remain a 404 — you cannot allocate credits to a
        workspace that has been removed.
        """
        owner = ws_setup["owner"]
        ws = ws_setup["ws"]

        ws.is_active = False
        db_session.commit()

        mock_auth(owner)
        resp = client.post(f"/api/v2/workspaces/{ws.id}/credits/allocate", json={"amount": 50})
        assert resp.status_code == 404, (
            f"Allocation to a soft-deleted workspace must 404, got {resp.status_code}: "
            f"{resp.text[:200]}"
        )


class TestCrossTenantWorkspace404AntiOracle:
    """SC4 anti-oracle invariants for the workspaces.py + members.py + invites.py +
    credits.py endpoints. Closes MISSING cells from
    12.4-01-cross-tenant-scaffold.md row 19 (workspace) + row 20 (workspace_credits).

    Each test uses the cross_tenant_ws fixture: org_b's owner is the caller
    and tries to access (or mutate) a workspace owned by org_a. Every
    endpoint must return 404 with a detail string byte-identical to the
    detail returned for a genuine nonexistent workspace id.

    Anti-oracle helper (tests/_helpers/anti_oracle.py, D-09 Path B) issues
    BOTH requests dynamically per-call and compares the detail strings —
    never against a hardcoded baseline.
    """

    def test_cross_tenant_get_workspace_404_anti_oracle(self, client, cross_tenant_ws):
        """SC4 row 19 READ: cross-tenant GET /workspaces/{id} returns 404 anti-oracle."""
        ws_a = cross_tenant_ws["ws_a"]
        assert_cross_tenant_404_anti_oracle(
            client,
            endpoint_template="/api/v2/workspaces/{id}",
            cross_tenant_resource_id=ws_a.id,
        )

    def test_cross_tenant_patch_workspace_404_anti_oracle(self, client, cross_tenant_ws):
        """SC4 row 19 WRITE: cross-tenant PATCH /workspaces/{id} returns 404 anti-oracle."""
        ws_a = cross_tenant_ws["ws_a"]
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="patch",
            endpoint_template="/api/v2/workspaces/{id}",
            cross_tenant_resource_id=ws_a.id,
            body={"name": "Cross-tenant hack attempt"},
        )

    def test_cross_tenant_delete_workspace_404_anti_oracle(self, client, cross_tenant_ws):
        """SC4 row 19 WRITE: cross-tenant DELETE /workspaces/{id} returns 404 anti-oracle.

        Note: the delete_workspace handler performs the owner check BEFORE
        _get_workspace_or_404, so attempting to delete another org's workspace
        as the OWN org's owner succeeds the owner check, then hits the
        404 path on the workspace lookup (org_b's owner is not org_a's
        owner — wait, both fixture users are owners of their OWN orgs, so
        the org from request.state.organization is org_b, and the owner
        check `org.owner_user_id == user.id` passes against org_b. The
        _get_workspace_or_404 then filters by org_b.id and returns 404.).
        """
        ws_a = cross_tenant_ws["ws_a"]
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="delete",
            endpoint_template="/api/v2/workspaces/{id}",
            cross_tenant_resource_id=ws_a.id,
        )

    def test_cross_tenant_patch_member_404_anti_oracle(self, client, db_session, cross_tenant_ws):
        """SC4 row 19 WRITE: cross-tenant PATCH /workspaces/{id}/members/{uid} returns 404.

        Setup: org_a has a workspace + a non-owner member. org_b's owner
        attempts to mutate that member's role. Both cross-tenant and
        nonexistent paths must 404 with byte-identical detail strings.

        The path's {id} placeholder is the MEMBER USER ID (per the helper's
        single-id template convention); ws_a.id is fixed in the path so
        the cross-tenant signal is via user_id only — but because the
        workspace itself belongs to org_a, the org_b owner's request
        passes the WorkspaceRole.ADMIN dependency (owner shortcut against
        org_b) and then dies on _get_member_or_404 (filtered by org_b.id).
        """
        ws_a = cross_tenant_ws["ws_a"]
        org_a = cross_tenant_ws["org_a"]
        # Add a non-owner editor member to org_a's workspace
        editor_a = _make_user(db_session, org_a, "usr_xt_a_editor", "editor-a@xt.test", "Editor A")
        _add_member(db_session, ws_a, editor_a, WorkspaceRole.EDITOR.value)
        db_session.commit()

        endpoint = f"/api/v2/workspaces/{ws_a.id}/members/{{id}}"
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="patch",
            endpoint_template=endpoint,
            cross_tenant_resource_id=editor_a.id,
            body={"role": "viewer"},
        )

    def test_cross_tenant_delete_member_404_anti_oracle(self, client, db_session, cross_tenant_ws):
        """SC4 row 19 WRITE: cross-tenant DELETE /workspaces/{id}/members/{uid} returns 404.

        Setup: org_a has a workspace + a non-owner member. org_b's owner
        attempts to remove that member via cross-tenant DELETE. Both paths
        must 404 with byte-identical detail strings.
        """
        ws_a = cross_tenant_ws["ws_a"]
        org_a = cross_tenant_ws["org_a"]
        editor_a = _make_user(
            db_session, org_a, "usr_xt_a_editor_d", "editor-a-d@xt.test", "Editor A D"
        )
        _add_member(db_session, ws_a, editor_a, WorkspaceRole.EDITOR.value)
        db_session.commit()

        endpoint = f"/api/v2/workspaces/{ws_a.id}/members/{{id}}"
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="delete",
            endpoint_template=endpoint,
            cross_tenant_resource_id=editor_a.id,
        )

    def test_cross_tenant_revoke_invite_404_anti_oracle(self, client, db_session, cross_tenant_ws):
        """SC4 row 19 WRITE: cross-tenant DELETE /workspaces/{id}/invites/{invite_id} returns 404.

        Setup: org_a has a workspace + a pending invite. org_b's owner
        attempts to revoke that invite. revoke_invite filters by
        organization_id == org_b.id, so the cross-tenant invite is invisible
        — 404 "Invite not found" — and the same handler returns the same
        detail for a genuinely nonexistent invite id.
        """
        ws_a = cross_tenant_ws["ws_a"]
        org_a = cross_tenant_ws["org_a"]
        owner_a = cross_tenant_ws["owner_a"]

        # Seed a pending email invite in org_a's workspace
        token_hash = hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()
        invite_a = WorkspaceInvite(
            id=generate_id("inv_"),
            workspace_id=ws_a.id,
            organization_id=org_a.id,
            role="viewer",
            method=InviteMethod.EMAIL.value,
            invitee_email="xt-target@xt.test",
            token_hash=token_hash,
            created_by=owner_a.id,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(days=7),
            is_revoked=False,
        )
        db_session.add(invite_a)
        db_session.commit()

        endpoint = f"/api/v2/workspaces/{ws_a.id}/invites/{{id}}"
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="delete",
            endpoint_template=endpoint,
            cross_tenant_resource_id=invite_a.id,
        )

    # ---- IDOR closure: the four endpoints Stop-the-lined in Plan 03 ----
    # These were deferred to a production fix (todo
    # 2026-05-23-ws-invite-cross-tenant-idor.md) because the endpoints had no
    # 404 path at all — they accepted a cross-tenant {workspace_id} and either
    # created an orphan row (invites) or silently created a foreign pool
    # (credits). The tenancy guard in workspaces/_common.py now 404s first.

    def test_cross_tenant_create_email_invite_404_anti_oracle(self, client, cross_tenant_ws):
        """SC4 row 19 WRITE: cross-tenant POST /workspaces/{id}/invites/email returns 404.

        org_b's owner must not create a WorkspaceInvite row keyed on org_a's
        workspace. Both cross-tenant and nonexistent paths now 404 with a
        byte-identical detail string (no invite row is written).
        """
        ws_a = cross_tenant_ws["ws_a"]
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="post",
            endpoint_template="/api/v2/workspaces/{id}/invites/email",
            cross_tenant_resource_id=ws_a.id,
            body={"email": "xt-attacker@example.com", "role": "viewer"},
        )

    def test_cross_tenant_create_link_invite_404_anti_oracle(self, client, cross_tenant_ws):
        """SC4 row 19 WRITE: cross-tenant POST /workspaces/{id}/invites/link returns 404."""
        ws_a = cross_tenant_ws["ws_a"]
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="post",
            endpoint_template="/api/v2/workspaces/{id}/invites/link",
            cross_tenant_resource_id=ws_a.id,
            body={"role": "viewer"},
        )

    def test_cross_tenant_get_credit_pool_404_anti_oracle(self, client, cross_tenant_ws):
        """SC4 row 20 READ: cross-tenant GET /workspaces/{id}/credits/ returns 404.

        Previously _get_or_create_pool queried by workspace_id alone and
        silently created a pool with organization_id=org_b, workspace_id=ws_a,
        returning 200. The guard now 404s before any row is created, and the
        pool query is org-scoped.
        """
        ws_a = cross_tenant_ws["ws_a"]
        assert_cross_tenant_404_anti_oracle(
            client,
            endpoint_template="/api/v2/workspaces/{id}/credits/",
            cross_tenant_resource_id=ws_a.id,
        )

    def test_cross_tenant_allocate_credits_404_anti_oracle(self, client, cross_tenant_ws):
        """SC4 row 20 WRITE: cross-tenant POST /workspaces/{id}/credits/allocate returns 404.

        org_b's owner must not move org_b credits into a pool keyed on org_a's
        workspace. The guard 404s before allocate_credits_to_pool runs, so no
        org-B balance is debited and no foreign pool is touched.
        """
        ws_a = cross_tenant_ws["ws_a"]
        assert_cross_tenant_404_anti_oracle_write(
            client,
            method="post",
            endpoint_template="/api/v2/workspaces/{id}/credits/allocate",
            cross_tenant_resource_id=ws_a.id,
            body={"amount": 100},
        )

    def test_cross_tenant_get_credit_pool_soft_deleted_404_anti_oracle(
        self, client, db_session, cross_tenant_ws
    ):
        """Finding #11 IDOR preservation: relaxing is_active for the pool GET
        (require_active=False) must NOT open cross-tenant reads. org_b reading
        org_a's SOFT-DELETED workspace pool still 404s (org_id is enforced
        regardless of is_active), with the same anti-oracle detail as a
        genuinely nonexistent id.
        """
        ws_a = cross_tenant_ws["ws_a"]
        ws_a.is_active = False
        db_session.commit()
        assert_cross_tenant_404_anti_oracle(
            client,
            endpoint_template="/api/v2/workspaces/{id}/credits/",
            cross_tenant_resource_id=ws_a.id,
        )
