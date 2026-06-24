#!/usr/bin/env python3
"""Ensure an admin user exists and print a fresh API key."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Inject scripts/ onto sys.path so ``_seed_common`` is importable when invoked
# as ``python scripts/ensure_admin_api_key.py`` without pip-install.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _seed_common import (  # noqa: E402  — path injection must happen first
    add_repo_to_path,
    get_or_create_org,
    get_or_create_user,
    resolve_id_prefixes,
    session_scope,
)

add_repo_to_path()

from app.config import settings  # noqa: E402  — repo path injection must happen first

# Defaults chain to the first-run bootstrap admin (SEED_ADMIN_*) so that
# running this script with no env mints an API key for THE admin created at
# first boot, instead of inventing a second one.
ADMIN_EMAIL = os.getenv("ENSURE_ADMIN_EMAIL") or settings.SEED_ADMIN_EMAIL or "admin@jaot.io"
ADMIN_NAME = os.getenv("ENSURE_ADMIN_NAME") or settings.SEED_ADMIN_NAME or "Bootstrap Admin"
ADMIN_PASSWORD = (
    os.getenv("ENSURE_ADMIN_PASSWORD") or settings.SEED_ADMIN_PASSWORD or "AdminPass123!"
)
ADMIN_KEY_NAME = os.getenv("ENSURE_ADMIN_KEY_NAME", "CLI Admin Key")
ADMIN_KEY_PREFIX = os.getenv("ENSURE_ADMIN_KEY_PREFIX") or "ok_live_"
ORG_NAME = os.getenv("ENSURE_ADMIN_ORG_NAME", "Primary Organization")


def main() -> None:
    from app.models import User
    from app.services.auth import APIKeyService

    with session_scope() as db:
        prefixes = resolve_id_prefixes(db)

        # If the admin already exists (e.g. created by the first-run
        # bootstrap), mint the key inside THEIR organization — never create
        # a parallel org for an existing user.
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if user is not None:
            user_created = org_created = False
            org_id = user.organization_id
            org_label = f"user's existing organization ({org_id})"
        else:
            org, org_created = get_or_create_org(
                db,
                name=ORG_NAME,
                prefix=prefixes["ID_PREFIX_ORGANIZATION"],
                credits_balance=10000,
            )
            user, user_created = get_or_create_user(
                db,
                email=ADMIN_EMAIL,
                name=ADMIN_NAME,
                password=ADMIN_PASSWORD,
                organization_id=org.id,
                role="admin",
                prefix=prefixes["ID_PREFIX_USER"],
            )
            org_id = org.id
            org_label = f"{org.name} ({org.id})"

        _, plaintext = APIKeyService.create_api_key(
            db=db,
            user_id=user.id,
            organization_id=org_id,
            name=ADMIN_KEY_NAME,
            prefix=ADMIN_KEY_PREFIX,
        )

        print("----------------------------------------")
        print("Admin provisioning summary")
        print("----------------------------------------")
        print(f"Organization: {org_label}{' [created]' if org_created else ''}")
        print(f"Admin user: {user.email} ({user.id}){' [created]' if user_created else ''}")
        if user_created:
            print(f"Password: {ADMIN_PASSWORD}")
        print(f"API key name: {ADMIN_KEY_NAME}")
        print("API key (copy now, only shown once):")
        print(plaintext)
        print("----------------------------------------")


if __name__ == "__main__":
    main()
