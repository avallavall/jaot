#!/usr/bin/env python3
"""Config doctor — tells a self-hoster what still needs filling in.

JAOT keeps infrastructure config in ``.env`` (DB, Redis, JWT secret) and all
*business* config in the ``platform_settings`` table, managed from the admin
panel. After ``docker compose up`` a fresh instance boots, but some settings
must be filled in before the platform is fully usable (e.g. SMTP, so email
verification and password reset actually send mail).

This script reads the live ``platform_settings`` and reports, grouped by
feature, what is missing — auto-discovering secrets from the settings registry
so it never drifts. Run it any time:

    docker compose exec api python scripts/doctor.py

Exit code is 0 when there are no critical gaps, 1 otherwise (handy for CI /
provisioning scripts).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.platform_setting import PlatformSetting  # noqa: E402
from app.services.settings_registry import (  # noqa: E402
    REGISTRY_BY_KEY,
    SETTINGS_REGISTRY,
)
from app.shared.db.session import SessionLocal  # noqa: E402

CRITICAL = "critical"
RECOMMENDED = "recommended"


def main() -> int:
    db = SessionLocal()
    try:
        rows = {s.key: s.value for s in db.query(PlatformSetting).all()}
    finally:
        db.close()

    def value(key: str) -> str | None:
        if key in rows:
            return rows[key]
        definition = REGISTRY_BY_KEY.get(key)
        return definition.default_value if definition else None

    def is_set(key: str) -> bool:
        if (value(key) or "").strip() != "":
            return True
        # Some secrets are supplied via the environment (.env) rather than the DB.
        return (os.environ.get(key) or "").strip() != ""

    findings: list[tuple[str, str, str]] = []  # (level, area, message)
    ok: list[str] = []

    # --- Email (signup verification + password reset depend on it) ---
    backend = (value("EMAIL_BACKEND") or "").strip().lower()
    if backend == "smtp":
        missing = [k for k in ("SMTP_HOST", "SMTP_USER", "EMAIL_FROM") if not is_set(k)]
        if missing:
            findings.append(
                (
                    CRITICAL,
                    "Email",
                    f"EMAIL_BACKEND=smtp but {', '.join(missing)} not set — "
                    "email verification and password reset will fail.",
                )
            )
        else:
            ok.append("Email: SMTP configured")
    else:
        findings.append(
            (
                RECOMMENDED,
                "Email",
                f"EMAIL_BACKEND={backend or 'unset'} — emails are not delivered to real "
                "inboxes (fine for local dev, not for production). Set EMAIL_BACKEND=smtp "
                "and the SMTP_* settings.",
            )
        )

    # --- AI assistant (works platform-wide via this key, or per-org via BYOK) ---
    if is_set("ANTHROPIC_API_KEY"):
        ok.append("AI assistant: platform Anthropic key configured")
    else:
        findings.append(
            (
                RECOMMENDED,
                "AI assistant",
                "ANTHROPIC_API_KEY not set — the AI formulation assistant won't work "
                "unless each organization brings its own key (BYOK).",
            )
        )

    # --- Any other secrets left empty (informational) ---
    # Infra secrets come from .env, not the admin panel — if the app is running
    # they're already set, so don't nag about them here.
    infra_keys = {"DATABASE_URL", "JWT_SECRET", "REDIS_URL", "CELERY_BROKER_URL"}
    handled = {"ANTHROPIC_API_KEY"} | infra_keys
    for definition in SETTINGS_REGISTRY:
        if not definition.is_secret or definition.key in handled:
            continue
        if not is_set(definition.key):
            findings.append(
                (RECOMMENDED, "Secret", f"{definition.key} not set — {definition.description}")
            )

    # --- Report ---
    criticals = [f for f in findings if f[0] == CRITICAL]
    recommended = [f for f in findings if f[0] == RECOMMENDED]

    print("\nJAOT config doctor")
    print("=" * 60)

    if criticals:
        print("\n\U0001f534 CRITICAL — the platform is not fully usable yet:")
        for _level, area, message in criticals:
            print(f"  [{area}] {message}")

    if recommended:
        print("\n\U0001f7e1 RECOMMENDED — optional, enable the features you need:")
        for _level, area, message in recommended:
            print(f"  [{area}] {message}")

    if ok:
        print("\n✅ OK:")
        for line in ok:
            print(f"  {line}")

    print("\n" + "=" * 60)
    if criticals:
        print(
            f"❌ {len(criticals)} critical gap(s). Fill them in the admin panel "
            "(Settings) and re-run this check."
        )
        return 1
    print("✅ No critical gaps — the platform is usable. Review the recommended items above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
