"""GDPR compliance tests: data export, account deletion, ToS acceptance."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import (
    APIKey,
    FormulationRating,
    LLMConversation,
    ModelBuilderDocument,
    ModelProject,
    ModelProjectListing,
    Notification,
    Organization,
    RefreshToken,
    SolveTrigger,
    User,
    Workspace,
)
from app.models.verification_request import VerificationRequest
from app.services.auth import PasswordService
from app.shared.utils.datetime_helpers import utcnow


def _make_user_with_password(db: Session, org: Organization, suffix: str = "") -> User:
    """Create a user with a password hash for deletion tests."""
    pw_hash = PasswordService.hash_password("TestPass123!")
    user = User(
        id=f"usr_gdpr{suffix}",
        email=f"gdpr{suffix}@example.com",
        name=f"GDPR User {suffix}",
        organization_id=org.id,
        role="admin",
        password_hash=pw_hash,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _seed_related_records(db: Session, user: User, org: Organization) -> None:
    """Seed child records that should be cascade-deleted."""
    from app.services.auth.api_key_service import APIKeyService

    APIKeyService.create_api_key(
        db=db,
        user_id=user.id,
        organization_id=org.id,
        name="gdpr-key",
        prefix="ok_gdpr_",
    )
    db.add(
        Notification(
            id="ntf_gdpr01",
            user_id=user.id,
            organization_id=org.id,
            title="Test notification",
            message="msg",
            type="info",
        )
    )
    # ADR-008: the legacy credit_transactions table has no ORM model; seed via
    # raw SQL so the deletion test still proves the raw-SQL purge empties it.
    db.execute(
        text(
            "INSERT INTO credit_transactions "
            "(id, organization_id, credits_amount, balance_after, earned_balance_after, "
            "description, transaction_type, created_at) "
            "VALUES ('txn_gdpr01', :org, 10, 10, 0, 'seed', 'credit', now())"
        ),
        {"org": org.id},
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            jti="jti_gdpr01",
            expires_at=utcnow(),
        )
    )
    # P1.5: model projects are the org's models — erasure must remove them (and
    # DB-level CASCADE must sweep the marketplace listing facet with them).
    db.add(
        ModelProject(
            id="mp_gdpr01",
            organization_id=org.id,
            name="GDPR Project",
            status="active",
        )
    )
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id="mp_gdpr01",
            name="gdpr-project",
            display_name="GDPR Project",
            description="d",
            author_organization_id=org.id,
        )
    )
    db.flush()


class TestDataExport:
    """GET /api/v2/user/data-export"""

    def test_data_export_returns_json_file(
        self, client, db_session, test_user, test_organization, mock_auth
    ):
        mock_auth(test_user)
        resp = client.get("/api/v2/user/data-export")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
        data = resp.json()
        assert "user" in data
        assert "organization" in data
        assert "models" in data

    def test_data_export_unauthenticated(self, client):
        resp = client.get("/api/v2/user/data-export")
        assert resp.status_code == 401

    def test_data_export_includes_all_sections(
        self, client, db_session, test_user, test_organization, mock_auth
    ):
        mock_auth(test_user)
        resp = client.get("/api/v2/user/data-export")
        data = resp.json()
        for key in [
            "exported_at",
            "user",
            "organization",
            "models",
            "executions",
            "api_keys",
            "notifications",
        ]:
            assert key in data, f"Missing key: {key}"

    def test_data_export_no_secrets(
        self, client, db_session, test_user, test_organization, mock_auth
    ):
        """API keys in export must NOT contain key_hash or plaintext."""
        from app.services.auth.api_key_service import APIKeyService

        APIKeyService.create_api_key(
            db=db_session,
            user_id=test_user.id,
            organization_id=test_organization.id,
            name="export-key",
            prefix="ok_test_",
        )
        db_session.flush()

        mock_auth(test_user)
        resp = client.get("/api/v2/user/data-export")
        data = resp.json()
        for ak in data["api_keys"]:
            assert "key_hash" not in ak
            assert "plaintext" not in ak

    # CONTRACT-TEST: the export never reads the payloads it does not write.
    #
    # It writes four scalars per run, and the default entity load pulled every
    # run's `input_data` and `result_data` with them — the compiled problem and
    # the whole solution. Measured on the development database against an
    # organization with 1,253 runs: 128 MB read to write 252 KB, and the request
    # took 19.5 seconds. There is no upper bound on rows and there must not be,
    # so the only thing holding the cost down is what each row loads.
    def test_the_export_does_not_read_the_payloads_it_never_writes(
        self, db_session, test_user, test_organization
    ):
        from sqlalchemy import event

        from app.models import ModelExecution
        from app.services.gdpr_service import export_user_data

        project = ModelProject(
            id="mp_gdpr_load",
            organization_id=test_organization.id,
            name="Heavy project",
            status="active",
            draft_model_json={"variables": [{"name": "x"}]},
        )
        db_session.add(project)
        db_session.flush()
        db_session.add(
            ModelExecution(
                id="exe_gdpr_load",
                organization_id=test_organization.id,
                model_project_id=project.id,
                status="completed",
                input_data={"variables": [{"name": "x"}]},
                result_data={"objective_value": 1.0},
            )
        )
        db_session.commit()
        db_session.expire_all()

        # Ask the database what it was actually sent. Inspecting the objects
        # afterwards cannot answer this: the session hands the same instances
        # back and refreshes what it needs, so everything reads as loaded.
        seen: list[str] = []

        def record(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        event.listen(db_session.bind, "before_cursor_execute", record)
        try:
            data = export_user_data(db_session, test_user, test_organization)
        finally:
            event.remove(db_session.bind, "before_cursor_execute", record)

        for column in ("input_data", "result_data"):
            assert not any(f"model_executions.{column}" in q for q in seen), (
                f"the export selected model_executions.{column}, which it never writes"
            )
        for column in ("draft_model_json", "draft_canvas_json"):
            assert not any(f"model_projects.{column}" in q for q in seen), (
                f"the export selected model_projects.{column}, which it never writes"
            )

        # And it still says everything it promised.
        assert any(m["id"] == "mp_gdpr_load" for m in data["models"])
        assert any(e["id"] == "exe_gdpr_load" for e in data["executions"])


class TestAccountDeletion:
    """DELETE /api/v2/user/account"""

    def test_account_deletion_success(self, client, db_session, test_organization, mock_auth):
        user = _make_user_with_password(db_session, test_organization, "del1")
        db_session.commit()
        mock_auth(user)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "TestPass123!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 200

        # User no longer in DB
        assert db_session.get(User, user.id) is None

    def test_account_deletion_wrong_password(
        self, client, db_session, test_organization, mock_auth
    ):
        user = _make_user_with_password(db_session, test_organization, "del2")
        db_session.commit()
        mock_auth(user)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "WrongPassword!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 401

    def test_account_deletion_sole_member_deletes_org(self, client, db_session, mock_auth):
        """If user is sole org member, the org must be deleted too."""
        org = Organization(
            id="org_sole01",
            name="Sole Org",
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()

        user = _make_user_with_password(db_session, org, "sole1")
        db_session.commit()
        mock_auth(user)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "TestPass123!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 200
        assert db_session.get(Organization, "org_sole01") is None

    def test_account_deletion_multi_member_preserves_org(
        self, client, db_session, test_organization, mock_auth
    ):
        """If other users exist in org, org is preserved."""
        user1 = _make_user_with_password(db_session, test_organization, "multi1")
        # second user in same org
        user2 = User(
            id="usr_gdprmulti2",
            email="gdprmulti2@example.com",
            name="Other",
            organization_id=test_organization.id,
            role="member",
            is_active=True,
        )
        db_session.add(user2)
        db_session.commit()
        mock_auth(user1)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "TestPass123!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 200
        # Org preserved
        assert db_session.get(Organization, test_organization.id) is not None
        # Deleted user gone
        assert db_session.get(User, user1.id) is None

    def test_account_deletion_cascading(self, client, db_session, mock_auth):
        """After deletion, no orphaned records."""
        org = Organization(
            id="org_casc01",
            name="Cascade Org",
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()

        user = _make_user_with_password(db_session, org, "casc1")
        _seed_related_records(db_session, user, org)
        db_session.commit()
        mock_auth(user)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "TestPass123!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 200

        # All related records gone
        assert db_session.query(APIKey).filter_by(user_id="usr_gdprcasc1").count() == 0
        assert db_session.query(Notification).filter_by(user_id="usr_gdprcasc1").count() == 0
        assert db_session.query(RefreshToken).filter_by(user_id="usr_gdprcasc1").count() == 0
        # Model projects erased (sole member ⇒ org data goes too), and the
        # listing facet swept by DB-level CASCADE
        assert db_session.query(ModelProject).filter_by(organization_id="org_casc01").count() == 0
        assert (
            db_session.query(ModelProjectListing).filter_by(model_project_id="mp_gdpr01").count()
            == 0
        )
        # ADR-008: legacy (ORM-less) money tables are purged via raw SQL — the
        # right-to-erasure must keep covering historic rows.
        remaining_txns = db_session.execute(
            text("SELECT count(*) FROM credit_transactions WHERE id = 'txn_gdpr01'")
        ).scalar()
        assert remaining_txns == 0


class TestDeleteCascadesAtTheDatabase:
    """The schema itself must let an account die.

    QA against production (2026-08-02): raw ``DELETE FROM organizations`` failed
    with a foreign-key violation on ``api_keys.organization_id``. The service
    deletes children by hand, but any table it forgets — it forgot several —
    blocks the erasure. These tests reproduce the failure at the level it was
    measured: plain SQL, no service in between.
    """

    @staticmethod
    def _seed_full_graph(db: Session, suffix: str) -> tuple[Organization, User]:
        """An org with one of everything that used to block its deletion."""
        org = Organization(id=f"org_fk{suffix}", name=f"FK Org {suffix}", is_active=True)
        db.add(org)
        db.flush()
        user = _make_user_with_password(db, org, f"fk{suffix}")
        db.add_all(
            [
                APIKey(
                    id=f"ak_fk{suffix}",
                    key_hash=f"hash_fk{suffix}",
                    key_prefix="ok_fk_",
                    user_id=user.id,
                    organization_id=org.id,
                ),
                RefreshToken(user_id=user.id, jti=f"jti_fk{suffix}", expires_at=utcnow()),
                VerificationRequest(organization_id=org.id, requested_by=user.id),
                Workspace(
                    id=f"ws_fk{suffix}",
                    organization_id=org.id,
                    name="ws",
                    created_by=user.id,
                ),
                SolveTrigger(
                    id=f"trg_fk{suffix}",
                    organization_id=org.id,
                    created_by=user.id,
                    name="trigger",
                    trigger_secret="x" * 64,
                    webhook_url="https://example.com/hook",
                ),
                ModelBuilderDocument(
                    id=f"mbd_fk{suffix}",
                    organization_id=org.id,
                    created_by=user.id,
                    name="doc",
                ),
            ]
        )
        conv = LLMConversation(organization_id=org.id, user_id=user.id)
        db.add(conv)
        db.flush()
        db.add(
            FormulationRating(
                conversation_id=conv.id,
                user_id=user.id,
                organization_id=org.id,
                rating="up",
                zone="studio",
            )
        )
        # Legacy ORM-less tables whose FKs also blocked the delete.
        db.execute(
            text(
                "INSERT INTO usage_records (id, organization_id, user_id, problem_type, "
                "credits_used, execution_time_ms, status, timestamp) "
                "VALUES (:id, :org, :usr, 'lp', 1, 1.0, 'completed', now())"
            ),
            {"id": f"ur_fk{suffix}", "org": org.id, "usr": user.id},
        )
        db.flush()
        return org, user

    # CONTRACT-TEST: DELETE FROM organizations succeeds and sweeps the account's data.
    def test_delete_organization_cascades(self, db_session: Session):
        org, user = self._seed_full_graph(db_session, "o1")
        org_id, user_id = org.id, user.id
        db_session.commit()

        # The exact statement production refused with a FK violation.
        db_session.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org_id})
        db_session.commit()
        # The rows died in the database; the identity map must not resurrect them.
        db_session.expunge_all()

        assert db_session.get(User, user_id) is None
        for model in (APIKey, LLMConversation, FormulationRating, VerificationRequest, Workspace):
            assert db_session.query(model).filter_by(organization_id=org_id).count() == 0, (
                f"{model.__name__} rows survived their organization"
            )
        assert db_session.query(RefreshToken).filter_by(user_id=user_id).count() == 0
        remaining = db_session.execute(
            text("SELECT count(*) FROM usage_records WHERE organization_id = :org"),
            {"org": org_id},
        ).scalar()
        assert remaining == 0, "legacy usage_records rows survived their organization"

    def test_delete_user_keeps_org_work_and_drops_attribution(self, db_session: Session):
        """Deleting one person must not delete the organization's work.

        Credentials and personal data die with the user; the workspace, trigger
        and builder document the user created stay, with ``created_by`` nulled.
        """
        org, user = self._seed_full_graph(db_session, "u1")
        user_id = user.id
        # A second member makes this an individual erasure, not an account one.
        other = User(
            id="usr_fkother",
            email="fkother@example.com",
            name="Other",
            organization_id=org.id,
            role="member",
            is_active=True,
        )
        db_session.add(other)
        db_session.commit()

        db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        db_session.commit()
        db_session.expunge_all()

        # Credentials and personal data are gone…
        assert db_session.query(APIKey).filter_by(user_id=user_id).count() == 0
        assert db_session.query(RefreshToken).filter_by(user_id=user_id).count() == 0
        assert db_session.query(LLMConversation).filter_by(user_id=user_id).count() == 0
        assert db_session.query(FormulationRating).filter_by(user_id=user_id).count() == 0

        # …while the organization's work survives, unattributed.
        for model, row_id in (
            (Workspace, "ws_fku1"),
            (SolveTrigger, "trg_fku1"),
            (ModelBuilderDocument, "mbd_fku1"),
        ):
            row = db_session.get(model, row_id)
            assert row is not None, f"{model.__name__} died with its creator"
            assert row.created_by is None, f"{model.__name__}.created_by not nulled"


@pytest.mark.usefixtures("enable_registration")
class TestTosAcceptance:
    """POST /api/v2/auth/signup/email sets tos_accepted_at."""

    def test_signup_sets_tos_accepted_at(self, client, db_session):
        resp = client.post(
            "/api/v2/auth/signup/email",
            json={
                "email": "tos@example.com",
                "name": "ToS User",
                "organization_name": "ToS Org",
                "password": "SecurePass1!",
                "confirm_password": "SecurePass1!",
                "tos_accepted": True,
            },
        )
        assert resp.status_code == 201
        user = db_session.query(User).filter_by(email="tos@example.com").first()
        assert user is not None
        assert user.tos_accepted_at is not None
