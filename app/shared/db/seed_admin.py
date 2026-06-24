"""First-run admin provisioning.

Two entry points share the same creation logic:

* ``bootstrap_first_run(db)`` — called from the API lifespan on every boot.
  When the ``users`` table is EMPTY and ``SEED_ADMIN_EMAIL`` /
  ``SEED_ADMIN_PASSWORD`` are set (see ``app/config.py``), it creates the
  initial organization + admin user so a fresh ``docker compose up`` yields
  a usable instance with zero manual steps. It never touches an instance
  that already has users.

* CLI — operator tool for existing deployments::

      ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD=secret123456 \\
          python -m app.shared.db.seed_admin

  Idempotent: promotes an existing user to admin, otherwise creates the
  user + organization and prints a fresh API key (CLI only — the automatic
  bootstrap never emits secrets to logs).
"""

import logging
import os
import sys

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Matches the public signup minimum (app/schemas/auth.py Field(min_length=12))
MIN_PASSWORD_LENGTH = 12


def _create_admin_with_org(
    db: Session,
    *,
    email: str,
    password: str,
    name: str,
    org_name: str = "",
    credits_override: int = 0,
):
    """Create the organization + admin user rows (no commit, no API key).

    Returns the (user, organization) pair; the caller owns the transaction.
    """
    from app.models import Organization, User  # noqa: PLC0415
    from app.services.auth import PasswordService  # noqa: PLC0415
    from app.services.platform_settings_service import PlatformSettingsService  # noqa: PLC0415
    from app.shared.utils.datetime_helpers import utcnow  # noqa: PLC0415
    from app.shared.utils.id_generator import generate_id  # noqa: PLC0415

    plan_config = PlatformSettingsService.get_plan_config_dynamic(db, "pro")

    org_prefix = PlatformSettingsService.get_str(db, "ID_PREFIX_ORGANIZATION")
    organization = Organization(
        id=generate_id(org_prefix),
        name=org_name or f"{name}'s Organization",
        plan="pro",
        credits_balance=credits_override if credits_override > 0 else plan_config["credits"],
        monthly_quota=plan_config["monthly_quota"],
        rate_limit_per_minute=plan_config["rate_limit_per_minute"],
        rate_limit_per_day=plan_config["rate_limit_per_day"],
        billing_email=email,
    )
    db.add(organization)

    usr_prefix = PlatformSettingsService.get_str(db, "ID_PREFIX_USER")
    user = User(
        id=generate_id(usr_prefix),
        email=email,
        name=name,
        organization_id=organization.id,
        role="admin",
        password_hash=PasswordService.hash_password(password),
        email_verified=True,
        tos_accepted_at=utcnow().replace(tzinfo=None),
    )
    db.add(user)
    db.flush()
    return user, organization


def bootstrap_first_run(db: Session) -> bool:
    """Create the initial admin + org on a pristine database. Lifespan hook.

    No-op (returns False) when SEED_ADMIN_* are not configured, when any
    user already exists, or when the password is too short. Never logs the
    password. The caller owns commit/rollback.
    """
    from app.config import settings  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415

    email = settings.SEED_ADMIN_EMAIL.strip().lower()
    password = settings.SEED_ADMIN_PASSWORD
    if not email or not password:
        return False

    if db.query(User.id).first() is not None:
        return False  # not a first run — never modify a live instance

    if len(password) < MIN_PASSWORD_LENGTH:
        logger.warning(
            "SEED_ADMIN_PASSWORD is shorter than %d characters — "
            "first-run admin NOT created. Fix it in .env and restart.",
            MIN_PASSWORD_LENGTH,
        )
        return False

    user, organization = _create_admin_with_org(
        db,
        email=email,
        password=password,
        name=settings.SEED_ADMIN_NAME,
        org_name=settings.SEED_ADMIN_ORG_NAME,
        credits_override=settings.SEED_ORG_CREDITS,
    )
    logger.info(
        "First-run bootstrap: admin %s created with organization '%s' "
        "(%s credits). Log in at the frontend to get started.",
        user.email,
        organization.name,
        organization.credits_balance,
    )
    return True


def seed_admin() -> None:
    """CLI entry point — see module docstring."""
    email = os.environ.get("ADMIN_EMAIL")
    password = os.environ.get("ADMIN_PASSWORD")
    name = os.environ.get("ADMIN_NAME", "Admin")

    if not email or not password:
        print(
            "Usage: ADMIN_EMAIL=x ADMIN_PASSWORD=x [ADMIN_NAME=x] python -m app.shared.db.seed_admin"
        )
        sys.exit(1)

    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"ERROR: ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters")
        sys.exit(1)

    from app.models import User
    from app.services.auth import APIKeyService
    from app.services.platform_settings_service import PlatformSettingsService
    from app.shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            if existing.role == "admin":
                print(f"Admin user {email} already exists. Nothing to do.")
                return
            existing.role = "admin"
            db.commit()
            print(f"Promoted existing user {email} to admin.")
            return

        user, organization = _create_admin_with_org(db, email=email, password=password, name=name)

        api_key_model, plaintext_key = APIKeyService.create_api_key(
            db=db,
            user_id=user.id,
            organization_id=organization.id,
            name=PlatformSettingsService.get_str(db, "API_KEY_DEFAULT_NAME"),
            prefix=PlatformSettingsService.get_str(db, "API_KEY_DEFAULT_PREFIX"),
        )

        db.commit()
        print(f"Admin user created: {email}")
        print(f"Organization: {organization.id}")
        print(f"API Key: {plaintext_key}")
        print("Plan: pro")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_admin()
