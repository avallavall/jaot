"""Team and workspace defects found driving the app with two accounts (QA, 2026-09-25).

Each test here failed on the code before the fix:

- an invited person with no account could never join: signup opened a new
  organization and the accept then refused it;
- a removed member opened the same link again and was back in;
- joining was logged as "Member Invited", and invite revokes and API keys were
  not audited at all;
- the member refusals the page shows were English in every locale;
- "Display Name" changed one column while every other screen read another;
- a wrong password on account deletion answered 401, which the web client reads
  as an expired session;
- the data export left out the profile, the memberships, the invites and the
  audit entries.
"""

import secrets
from datetime import timedelta

import pytest
from sqlalchemy import event

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
from app.services.auth import PasswordService
from app.services.workspace_invite_service import hash_invite_token
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

_PASSWORD = "Correct-Horse-9"


def _org(db, org_id: str) -> Organization:
    org = Organization(id=org_id, name=f"Org {org_id}", is_active=True)
    db.add(org)
    db.commit()
    return org


def _user(db, org: Organization, user_id: str, email: str, name: str = "Someone") -> User:
    user = User(
        id=user_id,
        email=email,
        name=name,
        organization_id=org.id,
        is_active=True,
        password_hash=PasswordService.hash_password(_PASSWORD),
    )
    db.add(user)
    db.commit()
    return user


def _workspace(db, org: Organization, owner: User) -> Workspace:
    now = utcnow()
    ws = Workspace(
        id=generate_id("wks_"),
        organization_id=org.id,
        name="Team WS",
        is_active=True,
        created_by=owner.id,
        created_at=now,
        updated_at=now,
    )
    db.add(ws)
    db.flush()
    db.add(
        WorkspaceMember(
            id=generate_id("wkm_"),
            workspace_id=ws.id,
            user_id=owner.id,
            organization_id=org.id,
            role=WorkspaceRole.ADMIN.value,
            joined_at=now,
        )
    )
    db.commit()
    return ws


def _invite(
    db,
    ws: Workspace,
    created_by: User,
    *,
    role: str = "editor",
    method: str = InviteMethod.LINK.value,
    email: str | None = None,
    created_at=None,
) -> str:
    plaintext = secrets.token_urlsafe(32)
    created = created_at or utcnow()
    db.add(
        WorkspaceInvite(
            id=generate_id("inv_"),
            workspace_id=ws.id,
            organization_id=ws.organization_id,
            role=role,
            method=method,
            invitee_email=email,
            token_hash=hash_invite_token(plaintext),
            created_by=created_by.id,
            created_at=created,
            expires_at=created + timedelta(days=7),
            is_revoked=False,
        )
    )
    db.commit()
    return plaintext


@pytest.fixture
def team(db_session):
    org = _org(db_session, "org_team_fix")
    owner = _user(db_session, org, "usr_team_owner", "owner@team.test", "Olive Owner")
    org.owner_user_id = owner.id
    db_session.commit()
    ws = _workspace(db_session, org, owner)
    return {"org": org, "owner": owner, "ws": ws}


def _signup(client, email: str, **extra):
    body = {
        "email": email,
        "name": "Max Member",
        "password": _PASSWORD,
        "confirm_password": _PASSWORD,
        "tos_accepted": True,
        **extra,
    }
    return client.post("/api/v2/auth/signup/email", json=body)


@pytest.mark.usefixtures("enable_registration")
class TestSignupFromAnInvite:
    def test_the_new_account_joins_the_inviting_organization(self, client, db_session, team):
        token = _invite(db_session, team["ws"], team["owner"], role="solver")
        orgs_before = db_session.query(Organization).count()

        resp = _signup(client, "max@example.com", invite_token=token)

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["organization_id"] == team["org"].id
        assert body["joined_workspace_id"] == team["ws"].id
        db_session.expire_all()
        user = db_session.query(User).filter(User.email == "max@example.com").one()
        assert user.organization_id == team["org"].id
        assert user.role == "member"
        # No organization was opened for them, and they did not become its owner.
        assert db_session.query(Organization).count() == orgs_before
        assert db_session.get(Organization, team["org"].id).owner_user_id == team["owner"].id
        member = (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == team["ws"].id,
                WorkspaceMember.user_id == user.id,
            )
            .one()
        )
        assert member.role == "solver"
        assert (
            db_session.query(AuditLog)
            .filter(
                AuditLog.workspace_id == team["ws"].id,
                AuditLog.action == AuditAction.MEMBER_JOIN.value,
                AuditLog.actor_id == user.id,
            )
            .count()
            == 1
        )

        # The session the signup opened sees the workspace.
        listed = client.get("/api/v2/workspaces/")
        assert listed.status_code == 200, listed.text
        assert team["ws"].id in [w["id"] for w in listed.json()["items"]]

    def test_an_email_invite_only_signs_up_its_own_address(self, client, db_session, team):
        token = _invite(
            db_session,
            team["ws"],
            team["owner"],
            method=InviteMethod.EMAIL.value,
            email="invited@example.com",
        )

        resp = _signup(client, "someone-else@example.com", invite_token=token)

        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "invite.other_email"
        assert db_session.query(User).filter(User.email == "someone-else@example.com").count() == 0

    def test_an_email_invite_signs_up_the_invited_address_once(self, client, db_session, team):
        token = _invite(
            db_session,
            team["ws"],
            team["owner"],
            method=InviteMethod.EMAIL.value,
            email="invited@example.com",
        )

        resp = _signup(client, "Invited@Example.com", invite_token=token)

        assert resp.status_code == 201, resp.text
        client.cookies.clear()
        again = _signup(client, "second@example.com", invite_token=token)
        assert again.status_code == 400, again.text
        assert again.json()["code"] == "invite.already_accepted"

    def test_a_token_that_is_no_invite_creates_nothing(self, client, db_session, team):
        resp = _signup(client, "ghost@example.com", invite_token="not-a-real-token")

        assert resp.status_code == 404, resp.text
        assert resp.json()["code"] == "invite.not_found"
        assert db_session.query(User).filter(User.email == "ghost@example.com").count() == 0

    def test_without_an_invite_an_organization_name_is_still_required(self, client, db_session):
        resp = _signup(client, "solo@example.com")
        assert resp.status_code == 422, resp.text

        ok = _signup(client, "solo@example.com", organization_name="Solo Org")
        assert ok.status_code == 201, ok.text


class TestRemovedMemberAndOldLinks:
    def test_a_removed_member_cannot_come_back_with_the_same_link(
        self, client, db_session, mock_auth, team
    ):
        member = _user(db_session, team["org"], "usr_team_member", "member@team.test", "Max")
        token = _invite(db_session, team["ws"], team["owner"], role="editor")

        mock_auth(member)
        joined = client.post("/api/v2/workspaces/invites/accept", json={"token": token})
        assert joined.status_code == 200, joined.text

        mock_auth(team["owner"])
        removed = client.delete(f"/api/v2/workspaces/{team['ws'].id}/members/{member.id}")
        assert removed.status_code == 204, removed.text

        mock_auth(member)
        again = client.post("/api/v2/workspaces/invites/accept", json={"token": token})
        assert again.status_code == 403, again.text
        assert again.json()["code"] == "invite.removed_member"
        assert (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == team["ws"].id,
                WorkspaceMember.user_id == member.id,
            )
            .count()
            == 0
        )

    def test_an_invite_created_after_the_removal_lets_them_back(
        self, client, db_session, mock_auth, team
    ):
        member = _user(db_session, team["org"], "usr_team_back", "back@team.test", "Back")
        old = _invite(db_session, team["ws"], team["owner"], role="editor")
        mock_auth(member)
        assert client.post("/api/v2/workspaces/invites/accept", json={"token": old}).is_success

        mock_auth(team["owner"])
        client.delete(f"/api/v2/workspaces/{team['ws'].id}/members/{member.id}")
        new = _invite(
            db_session,
            team["ws"],
            team["owner"],
            role="viewer",
            created_at=utcnow() + timedelta(seconds=1),
        )

        mock_auth(member)
        resp = client.post("/api/v2/workspaces/invites/accept", json={"token": new})
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "viewer"


class TestAuditTrail:
    def test_accepting_an_invite_is_logged_as_a_join(self, client, db_session, mock_auth, team):
        member = _user(db_session, team["org"], "usr_team_join", "join@team.test", "Joiner")
        token = _invite(db_session, team["ws"], team["owner"])

        mock_auth(member)
        assert client.post("/api/v2/workspaces/invites/accept", json={"token": token}).is_success

        actions = [
            row.action
            for row in db_session.query(AuditLog).filter(
                AuditLog.workspace_id == team["ws"].id, AuditLog.actor_id == member.id
            )
        ]
        assert actions == [AuditAction.MEMBER_JOIN.value]

    def test_revoking_an_invite_is_audited(self, client, db_session, mock_auth, team):
        _invite(db_session, team["ws"], team["owner"], role="viewer")
        invite = db_session.query(WorkspaceInvite).filter_by(workspace_id=team["ws"].id).one()

        mock_auth(team["owner"])
        resp = client.delete(f"/api/v2/workspaces/{team['ws'].id}/invites/{invite.id}")
        assert resp.status_code == 204, resp.text

        rows = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.workspace_id == team["ws"].id,
                AuditLog.action == AuditAction.INVITE_REVOKE.value,
            )
            .all()
        )
        assert [r.target_id for r in rows] == [invite.id]

    def test_creating_and_revoking_an_api_key_are_audited(
        self, authenticated_client, db_session, test_user
    ):
        created = authenticated_client.post("/api/v2/keys/", json={"name": "CI key"})
        assert created.status_code == 200, created.text
        key_id = created.json()["id"]

        revoked = authenticated_client.delete(f"/api/v2/keys/{key_id}")
        assert revoked.status_code == 200, revoked.text

        rows = (
            db_session.query(AuditLog)
            .filter(AuditLog.target_type == "api_key", AuditLog.target_id == key_id)
            .order_by(AuditLog.created_at)
            .all()
        )
        assert [r.action for r in rows] == [
            AuditAction.API_KEY_CREATE.value,
            AuditAction.API_KEY_REVOKE.value,
        ]
        assert all(r.actor_id == test_user.id for r in rows)
        assert all(r.organization_id == test_user.organization_id for r in rows)
        assert all(r.target_name == "CI key" for r in rows)


class TestMemberRefusalsAreCoded:
    def test_removing_the_owner_names_its_reason(self, client, db_session, mock_auth, team):
        admin = _user(db_session, team["org"], "usr_team_admin2", "admin2@team.test", "Admin 2")
        db_session.add(
            WorkspaceMember(
                id=generate_id("wkm_"),
                workspace_id=team["ws"].id,
                user_id=admin.id,
                organization_id=team["org"].id,
                role=WorkspaceRole.ADMIN.value,
                joined_at=utcnow(),
            )
        )
        db_session.commit()

        mock_auth(admin)
        resp = client.delete(f"/api/v2/workspaces/{team['ws'].id}/members/{team['owner'].id}")
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "workspace.owner_not_removable"

    def test_changing_your_own_role_names_its_reason(self, client, db_session, mock_auth, team):
        mock_auth(team["owner"])
        resp = client.patch(
            f"/api/v2/workspaces/{team['ws'].id}/members/{team['owner'].id}",
            json={"role": "viewer"},
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "workspace.own_role"

    def test_the_member_list_marks_the_owner(self, client, db_session, mock_auth, team):
        member = _user(db_session, team["org"], "usr_team_plain", "plain@team.test", "Plain")
        db_session.add(
            WorkspaceMember(
                id=generate_id("wkm_"),
                workspace_id=team["ws"].id,
                user_id=member.id,
                organization_id=team["org"].id,
                role=WorkspaceRole.VIEWER.value,
                joined_at=utcnow(),
            )
        )
        db_session.commit()

        mock_auth(member)
        resp = client.get(f"/api/v2/workspaces/{team['ws'].id}/members/")
        assert resp.status_code == 200, resp.text
        owners = {row["user_id"]: row["is_org_owner"] for row in resp.json()}
        assert owners == {team["owner"].id: True, member.id: False}


class TestOneName:
    def test_the_display_name_is_the_name_every_screen_shows(
        self, client, db_session, mock_auth, team
    ):
        mock_auth(team["owner"])
        saved = client.patch("/api/v2/users/profile", json={"display_name": "  Olive Owner QA "})
        assert saved.status_code == 200, saved.text

        db_session.expire_all()
        members = client.get(f"/api/v2/workspaces/{team['ws'].id}/members/").json()
        assert [m["user_name"] for m in members] == ["Olive Owner QA"]

        public = client.get(f"/api/v2/users/{team['owner'].id}/public").json()
        assert public["name"] == "Olive Owner QA"
        assert public["display_name"] == "Olive Owner QA"

        exported = client.get("/api/v2/user/data-export").json()
        assert exported["user"]["name"] == "Olive Owner QA"

        client.patch(f"/api/v2/workspaces/{team['ws'].id}", json={"name": "Renamed"})
        entry = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == AuditAction.WORKSPACE_UPDATE.value)
            .one()
        )
        assert entry.actor_name == "Olive Owner QA"

    def test_a_blank_display_name_is_refused(self, client, db_session, mock_auth, team):
        mock_auth(team["owner"])
        resp = client.patch("/api/v2/users/profile", json={"display_name": "   "})
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "profile.name_required"
        db_session.expire_all()
        assert db_session.get(User, team["owner"].id).name == "Olive Owner"


class TestDataExport:
    def test_the_export_carries_profile_teams_invites_and_audit(
        self, client, db_session, mock_auth, team
    ):
        owner = team["owner"]
        owner.bio = "Plans fleets."
        owner.linkedin_url = "https://linkedin.com/in/olive"
        db_session.commit()
        _invite(db_session, team["ws"], owner, role="viewer")

        mock_auth(owner)
        client.patch(f"/api/v2/workspaces/{team['ws'].id}", json={"name": "Exported WS"})
        data = client.get("/api/v2/user/data-export").json()

        assert data["user"]["bio"] == "Plans fleets."
        assert data["user"]["linkedin_url"] == "https://linkedin.com/in/olive"
        assert data["workspace_memberships"] == [
            {
                "workspace_id": team["ws"].id,
                "workspace_name": "Exported WS",
                "role": "admin",
                "joined_at": data["workspace_memberships"][0]["joined_at"],
                "invited_by": None,
            }
        ]
        assert [i["role"] for i in data["invites_sent"]] == ["viewer"]
        assert all("token_hash" not in i for i in data["invites_sent"])
        assert AuditAction.WORKSPACE_UPDATE.value in [a["action"] for a in data["audit_log"]]
        assert data["audit_log_truncated"] is False

    # CONTRACT-TEST: the export never reads the audit snapshots it does not write.
    def test_the_export_does_not_read_audit_snapshots(self, db_session, team):
        from app.services.gdpr_service import export_user_data

        db_session.add(
            AuditLog(
                id=generate_id("aud_"),
                organization_id=team["org"].id,
                workspace_id=team["ws"].id,
                actor_id=team["owner"].id,
                actor_name="Olive Owner",
                action=AuditAction.MODEL_EDIT.value,
                before_state={"model": "x" * 1000},
                after_state={"model": "y" * 1000},
                created_at=utcnow(),
            )
        )
        db_session.commit()

        seen: list[str] = []

        def record(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
            seen.append(statement)

        event.listen(db_session.bind, "before_cursor_execute", record)
        try:
            data = export_user_data(db_session, team["owner"], team["org"])
        finally:
            event.remove(db_session.bind, "before_cursor_execute", record)

        for column in ("before_state", "after_state", "metadata"):
            assert not any(f"audit_logs.{column}" in q for q in seen), column
        assert [a["action"] for a in data["audit_log"]] == [AuditAction.MODEL_EDIT.value]
