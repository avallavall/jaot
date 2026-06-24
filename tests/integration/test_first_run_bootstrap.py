"""First-run admin bootstrap — app/shared/db/seed_admin.bootstrap_first_run.

The lifespan calls this on every boot; the contract is that it provisions a
pristine database exactly once and is a strict no-op everywhere else.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.models import Organization, User
from app.services.auth.password_service import PasswordService
from app.shared.db.seed_admin import bootstrap_first_run
from app.shared.utils.id_generator import generate_id


def _configure_seed(
    monkeypatch: pytest.MonkeyPatch,
    email: str = "boot@example.com",
    password: str = "bootstrap-pass-123",
    credits: int = 0,
) -> None:
    monkeypatch.setattr(settings, "SEED_ADMIN_EMAIL", email)
    monkeypatch.setattr(settings, "SEED_ADMIN_PASSWORD", password)
    monkeypatch.setattr(settings, "SEED_ADMIN_NAME", "Boot Admin")
    monkeypatch.setattr(settings, "SEED_ADMIN_ORG_NAME", "")
    monkeypatch.setattr(settings, "SEED_ORG_CREDITS", credits)


class TestBootstrapFirstRun:
    # CONTRACT-TEST: a pristine DB + SEED_ADMIN_* config yields a verified
    # admin with an organization — the `docker compose up and log in` path.
    def test_creates_admin_and_org_on_empty_db(self, db_session, monkeypatch) -> None:
        _configure_seed(monkeypatch, credits=5000)

        created = bootstrap_first_run(db_session)
        db_session.commit()

        assert created is True
        user = db_session.query(User).filter(User.email == "boot@example.com").one()
        assert user.role == "admin"
        assert user.email_verified is True
        assert PasswordService.verify_password("bootstrap-pass-123", user.password_hash)

        org = db_session.query(Organization).filter(Organization.id == user.organization_id).one()
        assert org.credits_balance == 5000
        assert org.name == "Boot Admin's Organization"

    def test_credits_default_to_plan_config_when_not_overridden(
        self, db_session, monkeypatch
    ) -> None:
        _configure_seed(monkeypatch, credits=0)

        assert bootstrap_first_run(db_session) is True
        db_session.commit()

        org = db_session.query(Organization).one()
        assert org.plan == "pro"
        assert org.credits_balance > 0  # pro plan default, not zero

    # CONTRACT-TEST: the bootstrap never touches an instance that already
    # has users — restarting a live deployment with stale SEED_ADMIN_* env
    # must not create anything.
    def test_noop_when_any_user_exists(self, db_session, monkeypatch) -> None:
        org = Organization(id=generate_id("org_"), name="Existing Org")
        db_session.add(org)
        db_session.flush()
        db_session.add(
            User(
                id=generate_id("usr_"),
                email="existing@example.com",
                name="Existing",
                organization_id=org.id,
                role="member",
                password_hash=PasswordService.hash_password("irrelevant-pass-123"),
            )
        )
        db_session.commit()

        _configure_seed(monkeypatch)
        assert bootstrap_first_run(db_session) is False
        assert db_session.query(User).count() == 1

    def test_noop_when_not_configured(self, db_session, monkeypatch) -> None:
        _configure_seed(monkeypatch, email="", password="")
        assert bootstrap_first_run(db_session) is False
        assert db_session.query(User).count() == 0

    def test_noop_and_no_user_when_password_too_short(self, db_session, monkeypatch) -> None:
        _configure_seed(monkeypatch, password="short-pass")  # 10 < 12
        assert bootstrap_first_run(db_session) is False
        assert db_session.query(User).count() == 0

    def test_email_is_normalized(self, db_session, monkeypatch) -> None:
        _configure_seed(monkeypatch, email="  Boot@Example.COM ")
        assert bootstrap_first_run(db_session) is True
        db_session.commit()
        assert db_session.query(User).one().email == "boot@example.com"
