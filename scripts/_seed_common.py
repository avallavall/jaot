"""Shared bootstrap helpers for dev/seed scripts.

Consolidates repo-path injection, SessionLocal scoping, PSS-driven prefix
resolution, and org + user + API-key provisioning so each seed script
reduces to "config + one call per entity".
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.models import Organization, User

# Guard against an uninitialised PSS row: an empty prefix would silently
# produce IDs with no prefix, noisy to debug later.
_REQUIRED_PSS_PREFIXES: tuple[str, ...] = (
    "ID_PREFIX_ORGANIZATION",
    "ID_PREFIX_USER",
    "API_KEY_DEFAULT_PREFIX",
)


def add_repo_to_path() -> None:
    """Prepend the repo root to ``sys.path`` so ``app.*`` imports work.

    Idempotent — safe to call from any script that runs without
    ``pip install -e .``.
    """
    project_root = Path(__file__).resolve().parents[1]
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


@contextmanager
def session_scope() -> Iterator["Session"]:
    """Open + close a SessionLocal with automatic cleanup.

    No transactional wrapper: each call commits its own writes so a partial
    failure still leaves downstream entities recoverable.
    """
    from app.shared.db import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def resolve_id_prefixes(db: "Session") -> dict[str, str]:
    """Fetch every required ID / API-key prefix from platform_settings.

    Raises ``RuntimeError`` if any required row is missing or blank — a
    silent empty prefix would produce IDs that collide with arbitrary
    string values, so fail loudly at script start.
    """
    from app.services.platform_settings_service import PlatformSettingsService

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key in _REQUIRED_PSS_PREFIXES:
        value = PlatformSettingsService.get_str(db, key)
        if not value:
            missing.append(key)
        else:
            resolved[key] = value
    if missing:
        raise RuntimeError(
            "platform_settings rows missing or blank for required prefixes: "
            f"{', '.join(missing)}. Run `alembic -c infra/alembic.ini upgrade head` "
            "(or start the API once) before seeding."
        )
    return resolved


def get_or_create_org(
    db: "Session",
    name: str,
    prefix: str,
    credits_balance: int,
) -> tuple["Organization", bool]:
    """Return ``(org, created)`` for the named organization.

    Caller provides the ID prefix (from :func:`resolve_id_prefixes`) so no
    extra PSS round-trip is needed.
    """
    from app.models import Organization
    from app.shared.utils.id_generator import generate_id

    existing = db.query(Organization).filter(Organization.name == name).first()
    if existing is not None:
        return existing, False

    org = Organization(
        id=generate_id(prefix),
        name=name,
        credits_balance=credits_balance,
        is_active=True,
    )
    db.add(org)
    db.commit()
    return org, True


def get_or_create_user(
    db: "Session",
    *,
    email: str,
    name: str,
    password: str,
    organization_id: str,
    role: str,
    prefix: str,
) -> tuple["User", bool]:
    """Return ``(user, created)`` for the email.

    Caller is responsible for any extra org-owner wiring.
    """
    from app.models import User
    from app.services.auth.password_service import PasswordService
    from app.shared.utils.id_generator import generate_id

    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        return existing, False

    user = User(
        id=generate_id(prefix),
        email=email,
        name=name,
        organization_id=organization_id,
        role=role,
        is_active=True,
        password_hash=PasswordService.hash_password(password),
        email_verified=True,
    )
    db.add(user)
    db.commit()
    return user, True


__all__ = [
    "add_repo_to_path",
    "get_or_create_org",
    "get_or_create_user",
    "resolve_id_prefixes",
    "session_scope",
]
