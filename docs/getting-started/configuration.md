# Configuration

JAOT keeps configuration in **two layers**, on purpose:

| Layer | Where | What | When |
|---|---|---|---|
| **Infrastructure** | `.env` file | DB, Redis, Celery broker, JWT secret, frontend URL | Loaded at boot, before the database is available |
| **Business config** | `platform_settings` table | LLM, email/SMTP, billing, security & rate limits, feature flags, object storage… | Managed at runtime from the **admin panel** (Settings) |

You only edit `.env` once (infra). Everything else is changed live from the admin
panel — no redeploy. The source of truth for every business setting (type,
default, category, whether it's a secret) is `app/services/settings_registry.py`.

---

## After first boot: run the config doctor

A fresh `docker compose up` boots a working instance, but a few settings must be
filled in before the platform is fully usable (e.g. SMTP, so signup verification
and password reset actually send mail). Run the doctor any time to see what's
missing:

```bash
docker compose exec api python scripts/doctor.py
```

It reads the live `platform_settings`, groups gaps by feature, and prints a
verdict:

- 🔴 **CRITICAL** — the platform isn't fully usable yet (exit code 1).
- 🟡 **RECOMMENDED** — optional features you can enable as needed.
- ✅ **OK** — already configured.

---

## What to fill in for a usable instance

Open `/admin → Settings` in the app and configure, at minimum:

- **Email (SMTP)** — required for signup email verification and password reset.
  Set `EMAIL_BACKEND=smtp` plus `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` and
  `EMAIL_FROM`. The default `console` backend only logs emails (fine for local
  dev, not for production).
- **AI assistant** — set a platform-wide `ANTHROPIC_API_KEY`, **or** let each
  organization bring its own key (BYOK) from its workspace settings. Without
  either, the AI formulation assistant is disabled but the rest of the platform
  works.

Optional, enable only if you need them:

- **Billing** — only relevant when `MONETIZATION_ENABLED` is on; then you must
  provide Stripe keys. Off by default (the marketplace is free).
- **Object storage** — `STORAGE_*` for image uploads.
- **Security / rate limits** — sensible defaults ship out of the box; tune login
  and other limits under the Security category if needed.

---

## `.env` reference (infrastructure)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis (rate limiting, Celery result backend) |
| `CELERY_BROKER_URL` | RabbitMQ broker for async tasks |
| `JWT_SECRET` | Secret for signing JWTs (required when `DEBUG=False`) |
| `FRONTEND_URL` | Public URL of the frontend |

Copy `.env.example` to `.env` and fill these in before the first boot.
