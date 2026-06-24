"""Organization management tests (Task 3.7).

Tests workspace-based member management endpoints:
- List workspace members
- Invite a user to a workspace (email invite)
- Change user role within a workspace
- Remove member from a workspace
- Permission enforcement (different roles have different access)
- Organization owner/admin protections

Note: JAOT uses workspace-based member management (not org-level).
Organization owners bypass all workspace permission checks.
Workspaces are the collaboration boundary with role-based access:
  admin > editor > solver > viewer.

These tests use the real PostgreSQL test database (not mocks).
"""

import pytest

from app.models.organization import Organization
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceRole,
)
from app.models.workspace_credits import WorkspaceCreditPool
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _create_org(db, org_id="org_mgmt001", balance=1000):
    """Create a test organization."""
    org = Organization(
        id=org_id,
        name="Mgmt Test Org",
        credits_balance=balance,
        is_active=True,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _create_user(db, org, user_id, email, name="Test User", role="member"):
    """Create a test user belonging to org."""
    user = User(
        id=user_id,
        email=email,
        name=name,
        organization_id=org.id,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_workspace(db, org, owner):
    """Create a workspace with owner as admin member and an empty credit pool."""
    now = utcnow()
    ws = Workspace(
        id=generate_id("wks_"),
        organization_id=org.id,
        name="Test Workspace",
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
    """Add a user as a member to a workspace."""
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


@pytest.fixture
def org_setup(db_session):
    """Create an org with an owner and a workspace."""
    org = _create_org(db_session, "org_mgmt_test")
    owner = _create_user(db_session, org, "usr_mgmt_owner", "owner@mgmt.test", "Org Owner", "admin")
    org.owner_user_id = owner.id
    db_session.commit()
    ws = _create_workspace(db_session, org, owner)
    return {"org": org, "owner": owner, "ws": ws}


@pytest.fixture
def org_with_members(org_setup, db_session):
    """Extend org_setup with members at different roles."""
    org = org_setup["org"]
    ws = org_setup["ws"]

    admin = _create_user(
        db_session, org, "usr_mgmt_admin", "admin@mgmt.test", "Admin User", "admin"
    )
    editor = _create_user(db_session, org, "usr_mgmt_editor", "editor@mgmt.test", "Editor User")
    solver = _create_user(db_session, org, "usr_mgmt_solver", "solver@mgmt.test", "Solver User")
    viewer = _create_user(db_session, org, "usr_mgmt_viewer", "viewer@mgmt.test", "Viewer User")

    _add_member(db_session, ws, admin, WorkspaceRole.ADMIN.value)
    _add_member(db_session, ws, editor, WorkspaceRole.EDITOR.value)
    _add_member(db_session, ws, solver, WorkspaceRole.SOLVER.value)
    _add_member(db_session, ws, viewer, WorkspaceRole.VIEWER.value)

    return {
        **org_setup,
        "admin": admin,
        "editor": editor,
        "solver": solver,
        "viewer": viewer,
    }


class TestListMembers:
    """Tests for GET /api/v2/workspaces/{ws_id}/members/."""

    def test_list_members_as_viewer(self, client, mock_auth, org_with_members):
        """Viewer can list all workspace members."""
        viewer = org_with_members["viewer"]
        ws = org_with_members["ws"]

        mock_auth(viewer)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/members/")
        assert resp.status_code == 200

        data = resp.json()
        # owner + admin + editor + solver + viewer = 5
        assert len(data) >= 5
        user_ids = [m["user_id"] for m in data]
        assert viewer.id in user_ids

    def test_list_members_contains_user_details(self, client, mock_auth, org_with_members):
        """Member list includes user_name, user_email, role."""
        viewer = org_with_members["viewer"]
        ws = org_with_members["ws"]

        mock_auth(viewer)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/members/")
        assert resp.status_code == 200

        data = resp.json()
        for member in data:
            assert "user_name" in member
            assert "user_email" in member
            assert "role" in member
            assert member["role"] in {"admin", "editor", "solver", "viewer"}

    def test_list_members_as_owner(self, client, mock_auth, org_with_members):
        """Org owner can list members (owner bypasses role checks).

        Also asserts the owner actually sees the full workspace roster
        rather than an empty list — verifies the owner-bypass synthesis
        produces the same data a real member would see.
        """
        owner = org_with_members["owner"]
        ws = org_with_members["ws"]

        mock_auth(owner)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/members/")
        assert resp.status_code == 200

        data = resp.json()
        # owner + admin + editor + solver + viewer = 5
        assert len(data) >= 5
        user_ids = [m["user_id"] for m in data]
        assert owner.id in user_ids

    def test_list_members_non_member_gets_403(self, client, mock_auth, org_setup, db_session):
        """User not in the workspace gets 403."""
        org = org_setup["org"]
        ws = org_setup["ws"]
        outsider = _create_user(db_session, org, "usr_outsider", "outsider@mgmt.test", "Outsider")

        mock_auth(outsider)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/members/")
        assert resp.status_code == 403


class TestInviteUser:
    """Tests for POST /api/v2/workspaces/{ws_id}/invites/email."""

    def test_create_email_invite_as_admin(self, client, mock_auth, org_with_members):
        """Admin can create an email invite."""
        admin = org_with_members["admin"]
        ws = org_with_members["ws"]

        mock_auth(admin)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "newuser@example.com", "role": "editor"},
        )
        assert resp.status_code == 201

        data = resp.json()
        assert data["role"] == "editor"
        assert data["method"] == "email"
        assert data["invitee_email"] == "newuser@example.com"
        assert data["workspace_id"] == ws.id
        assert data["is_revoked"] is False

    def test_create_email_invite_as_owner(self, client, mock_auth, org_setup):
        """Org owner can create invites (owner bypass)."""
        owner = org_setup["owner"]
        ws = org_setup["ws"]

        mock_auth(owner)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "invited@example.com", "role": "viewer"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["invitee_email"] == "invited@example.com"
        assert data["role"] == "viewer"
        assert data["workspace_id"] == ws.id

    def test_create_email_invite_as_viewer_fails(self, client, mock_auth, org_with_members):
        """Viewer cannot create invites (needs admin role)."""
        viewer = org_with_members["viewer"]
        ws = org_with_members["ws"]

        mock_auth(viewer)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "nope@example.com", "role": "viewer"},
        )
        assert resp.status_code == 403

    def test_create_link_invite_as_admin(self, client, mock_auth, org_with_members):
        """Admin can create a shareable link invite."""
        admin = org_with_members["admin"]
        ws = org_with_members["ws"]

        mock_auth(admin)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/link",
            json={"role": "solver"},
        )
        assert resp.status_code == 201

        data = resp.json()
        assert "invite_url" in data
        assert "expires_at" in data

    def test_list_pending_invites(self, client, mock_auth, org_with_members):
        """Admin can list pending invites."""
        admin = org_with_members["admin"]
        ws = org_with_members["ws"]

        mock_auth(admin)
        client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "pending@example.com", "role": "viewer"},
        )

        resp = client.get(f"/api/v2/workspaces/{ws.id}/invites/")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 1
        emails = [inv["invitee_email"] for inv in data if inv.get("invitee_email")]
        assert "pending@example.com" in emails


class TestChangeRole:
    """Tests for PATCH /api/v2/workspaces/{ws_id}/members/{user_id}."""

    def test_admin_can_change_member_role(self, client, mock_auth, org_with_members):
        """Admin can promote a viewer to editor."""
        owner = org_with_members["owner"]
        viewer = org_with_members["viewer"]
        ws = org_with_members["ws"]

        mock_auth(owner)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{viewer.id}",
            json={"role": "editor"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "editor"

    def test_admin_can_demote_member(self, client, mock_auth, org_with_members):
        """Admin can demote an editor to viewer."""
        owner = org_with_members["owner"]
        editor = org_with_members["editor"]
        ws = org_with_members["ws"]

        mock_auth(owner)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{editor.id}",
            json={"role": "viewer"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "viewer"

    def test_editor_cannot_change_roles(self, client, mock_auth, org_with_members):
        """Editor cannot change another member's role (needs admin)."""
        editor = org_with_members["editor"]
        solver = org_with_members["solver"]
        ws = org_with_members["ws"]

        mock_auth(editor)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{solver.id}",
            json={"role": "viewer"},
        )
        assert resp.status_code == 403

    def test_cannot_change_own_role(self, client, mock_auth, org_with_members):
        """Admin cannot change their own role."""
        admin = org_with_members["admin"]
        ws = org_with_members["ws"]

        mock_auth(admin)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{admin.id}",
            json={"role": "viewer"},
        )
        assert resp.status_code == 400
        assert "own role" in resp.json()["detail"].lower()

    def test_cannot_change_org_owner_role(self, client, mock_auth, org_with_members, db_session):
        """Cannot change the org owner's workspace role."""
        admin = org_with_members["admin"]
        owner = org_with_members["owner"]
        ws = org_with_members["ws"]

        mock_auth(admin)
        resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{owner.id}",
            json={"role": "viewer"},
        )
        assert resp.status_code == 400
        assert "owner" in resp.json()["detail"].lower()


class TestRemoveMember:
    """Tests for DELETE /api/v2/workspaces/{ws_id}/members/{user_id}."""

    def test_admin_can_remove_member(self, client, mock_auth, org_with_members, db_session):
        """Admin can remove a viewer from the workspace."""
        owner = org_with_members["owner"]
        viewer = org_with_members["viewer"]
        ws = org_with_members["ws"]

        mock_auth(owner)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/members/{viewer.id}")
        assert resp.status_code == 204

        # Verify the member is actually removed
        remaining = (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == viewer.id,
            )
            .first()
        )
        assert remaining is None

    def test_editor_cannot_remove_member(self, client, mock_auth, org_with_members):
        """Editor cannot remove members (needs admin)."""
        editor = org_with_members["editor"]
        solver = org_with_members["solver"]
        ws = org_with_members["ws"]

        mock_auth(editor)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/members/{solver.id}")
        assert resp.status_code == 403

    def test_cannot_remove_self(self, client, mock_auth, org_with_members):
        """Admin cannot remove themselves."""
        admin = org_with_members["admin"]
        ws = org_with_members["ws"]

        mock_auth(admin)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/members/{admin.id}")
        assert resp.status_code == 400
        assert "yourself" in resp.json()["detail"].lower()

    def test_cannot_remove_org_owner(self, client, mock_auth, org_with_members):
        """Cannot remove the org owner from a workspace."""
        admin = org_with_members["admin"]
        owner = org_with_members["owner"]
        ws = org_with_members["ws"]

        mock_auth(admin)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/members/{owner.id}")
        assert resp.status_code == 400
        assert "owner" in resp.json()["detail"].lower()

    def test_remove_nonexistent_member_returns_404(self, client, mock_auth, org_with_members):
        """Removing a user who is not a member returns 404."""
        owner = org_with_members["owner"]
        ws = org_with_members["ws"]

        mock_auth(owner)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/members/usr_nonexistent")
        assert resp.status_code == 404


class TestPermissionEnforcement:
    """Tests that different workspace roles have different access levels."""

    def test_viewer_can_list_but_not_modify(self, client, mock_auth, org_with_members):
        """Viewer can GET members but cannot PATCH roles."""
        viewer = org_with_members["viewer"]
        solver = org_with_members["solver"]
        ws = org_with_members["ws"]

        mock_auth(viewer)

        # Can list
        list_resp = client.get(f"/api/v2/workspaces/{ws.id}/members/")
        assert list_resp.status_code == 200

        # Cannot change role
        patch_resp = client.patch(
            f"/api/v2/workspaces/{ws.id}/members/{solver.id}",
            json={"role": "viewer"},
        )
        assert patch_resp.status_code == 403

    def test_solver_cannot_create_invites(self, client, mock_auth, org_with_members):
        """Solver role cannot create invites (needs admin)."""
        solver = org_with_members["solver"]
        ws = org_with_members["ws"]

        mock_auth(solver)
        resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "test@example.com", "role": "viewer"},
        )
        assert resp.status_code == 403

    def test_non_member_cannot_access_workspace(self, client, mock_auth, org_setup, db_session):
        """A user from the same org but NOT in the workspace gets 403."""
        org = org_setup["org"]
        ws = org_setup["ws"]
        outsider = _create_user(db_session, org, "usr_perm_out", "perm_out@mgmt.test", "Outsider")

        mock_auth(outsider)
        resp = client.get(f"/api/v2/workspaces/{ws.id}/members/")
        assert resp.status_code == 403

    def test_workspace_creation_restricted_to_owner(self, client, mock_auth, org_with_members):
        """Only the org owner can create workspaces."""
        admin = org_with_members["admin"]

        # Admin (not owner) cannot create workspace
        mock_auth(admin)
        resp = client.post(
            "/api/v2/workspaces/",
            json={"name": "Admin Workspace"},
        )
        assert resp.status_code == 403

    def test_owner_can_create_workspace(self, client, mock_auth, org_setup):
        """Org owner can create a new workspace."""
        owner = org_setup["owner"]

        mock_auth(owner)
        resp = client.post(
            "/api/v2/workspaces/",
            json={"name": "Owner New Workspace", "description": "Created by owner"},
        )
        assert resp.status_code == 201

        data = resp.json()
        assert data["name"] == "Owner New Workspace"
        assert data["member_count"] == 1  # owner auto-added

    def test_workspace_delete_restricted_to_owner(self, client, mock_auth, org_with_members):
        """Only the org owner can delete (soft-delete) a workspace."""
        admin = org_with_members["admin"]
        ws = org_with_members["ws"]

        mock_auth(admin)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}")
        assert resp.status_code == 403


class TestOwnerProtections:
    """Tests for org owner protections in workspace management."""

    def test_owner_bypass_no_membership_needed(self, client, mock_auth, org_setup, db_session):
        """Org owner can access workspace detail even without a WorkspaceMember row.

        The owner bypass in RequireViewer synthesizes a virtual admin member.
        """
        org = org_setup["org"]
        owner = org_setup["owner"]

        now = utcnow()
        ws2 = Workspace(
            id=generate_id("wks_"),
            organization_id=org.id,
            name="No Member WS",
            is_active=True,
            created_by=owner.id,
            created_at=now,
            updated_at=now,
        )
        db_session.add(ws2)
        # Add a different user as the only explicit member
        other = _create_user(db_session, org, "usr_ws2_other", "other@mgmt.test", "Other User")
        other_member = WorkspaceMember(
            id=generate_id("wkm_"),
            workspace_id=ws2.id,
            user_id=other.id,
            organization_id=org.id,
            role=WorkspaceRole.VIEWER.value,
            joined_at=now,
        )
        db_session.add(other_member)
        pool = WorkspaceCreditPool(
            id=generate_id("wcp_"),
            workspace_id=ws2.id,
            organization_id=org.id,
            allocated_credits=0,
            used_credits=0,
            created_at=now,
            updated_at=now,
        )
        db_session.add(pool)
        db_session.commit()

        mock_auth(owner)
        resp = client.get(f"/api/v2/workspaces/{ws2.id}")
        assert resp.status_code == 200

    def test_owner_can_list_all_workspaces(self, client, mock_auth, org_setup, db_session):
        """Org owner sees ALL workspaces in the org, including ones the owner
        is NOT an explicit member of. Creates two extra workspaces where
        only another user is a member, then asserts the owner sees all three
        (the fixture-provided one plus the two we add here)."""
        org = org_setup["org"]
        owner = org_setup["owner"]

        other = _create_user(
            db_session, org, "usr_other_ws", "other_ws@mgmt.test", "Other User", "member"
        )

        now = utcnow()
        extra_ws_ids = []
        for idx in range(2):
            ws = Workspace(
                id=generate_id("wks_"),
                organization_id=org.id,
                name=f"Extra Workspace {idx}",
                is_active=True,
                created_by=other.id,
                created_at=now,
                updated_at=now,
            )
            db_session.add(ws)
            db_session.flush()
            extra_ws_ids.append(ws.id)

            # owner is NOT added as a member; only the other user is
            member = WorkspaceMember(
                id=generate_id("wkm_"),
                workspace_id=ws.id,
                user_id=other.id,
                organization_id=org.id,
                role=WorkspaceRole.VIEWER.value,
                joined_at=now,
            )
            db_session.add(member)
            pool = WorkspaceCreditPool(
                id=generate_id("wcp_"),
                workspace_id=ws.id,
                organization_id=org.id,
                allocated_credits=0,
                used_credits=0,
                created_at=now,
                updated_at=now,
            )
            db_session.add(pool)
        db_session.commit()

        mock_auth(owner)
        resp = client.get("/api/v2/workspaces/")
        assert resp.status_code == 200

        data = resp.json()
        # Fixture-provided ws + 2 extras = 3
        assert data["total"] == 3
        returned_ids = [w["id"] for w in data.get("items", [])]
        for ws_id in extra_ws_ids:
            assert ws_id in returned_ids

    def test_revoke_invite_as_admin(self, client, mock_auth, org_with_members, db_session):
        """Admin can revoke a pending invite."""
        admin = org_with_members["admin"]
        ws = org_with_members["ws"]

        mock_auth(admin)

        create_resp = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "revoke@example.com", "role": "viewer"},
        )
        assert create_resp.status_code == 201
        invite_id = create_resp.json()["id"]

        # Revoke it
        revoke_resp = client.delete(f"/api/v2/workspaces/{ws.id}/invites/{invite_id}")
        assert revoke_resp.status_code == 204

        # Verify it's revoked in the DB
        invite = db_session.query(WorkspaceInvite).filter(WorkspaceInvite.id == invite_id).first()
        assert invite.is_revoked is True


class TestRemoveMemberCascade:
    """Removing a workspace member who has created pending invites and
    a workspace-scoped credit pool must not orphan any rows.

    The member row is deleted, but workspace_invites.created_by is a plain
    string (not a FK with cascade), and workspace_credit_pools is scoped
    to the workspace rather than the member, so both should survive the
    removal with consistent values.
    """

    def test_remove_member_with_open_invites_and_credit_pool(
        self, client, mock_auth, org_with_members, db_session
    ):
        owner = org_with_members["owner"]
        admin = org_with_members["admin"]
        ws = org_with_members["ws"]

        # Admin (who will be removed) creates two pending invites.
        mock_auth(admin)
        resp1 = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "cascade1@example.com", "role": "viewer"},
        )
        assert resp1.status_code == 201
        invite1_id = resp1.json()["id"]

        resp2 = client.post(
            f"/api/v2/workspaces/{ws.id}/invites/email",
            json={"email": "cascade2@example.com", "role": "editor"},
        )
        assert resp2.status_code == 201
        invite2_id = resp2.json()["id"]

        # Capture the workspace credit pool for this workspace
        pool_before = (
            db_session.query(WorkspaceCreditPool)
            .filter(WorkspaceCreditPool.workspace_id == ws.id)
            .one()
        )
        pool_id = pool_before.id

        # Owner removes the admin from the workspace
        mock_auth(owner)
        resp = client.delete(f"/api/v2/workspaces/{ws.id}/members/{admin.id}")
        assert resp.status_code == 204

        # The workspace member row is gone
        removed = (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == ws.id,
                WorkspaceMember.user_id == admin.id,
            )
            .first()
        )
        assert removed is None

        # Both invites still exist (not cascaded) and are NOT revoked
        invite1 = db_session.query(WorkspaceInvite).filter(WorkspaceInvite.id == invite1_id).one()
        invite2 = db_session.query(WorkspaceInvite).filter(WorkspaceInvite.id == invite2_id).one()
        assert invite1.is_revoked is False
        assert invite2.is_revoked is False
        # created_by still points at the now-removed admin (string, not FK)
        assert invite1.created_by == admin.id
        assert invite2.created_by == admin.id

        # The credit pool still exists with the same id — not orphaned, not doubled
        pools = (
            db_session.query(WorkspaceCreditPool)
            .filter(WorkspaceCreditPool.workspace_id == ws.id)
            .all()
        )
        assert len(pools) == 1
        assert pools[0].id == pool_id

        # The removed admin user row itself is untouched (the FK is member-only)
        user_still_there = db_session.query(User).filter(User.id == admin.id).one()
        assert user_still_there.id == admin.id
