# Plausible self-hosted — local config files

This directory holds the ClickHouse server-side configuration overrides bind-mounted into
the `plausible_events_db` container by `deploy/docker-compose.prod.yml`. The four XML files
are copied **verbatim** from `plausible/community-edition` at tag `v3.2.0` and MUST NOT be
edited by hand — Plausible has already tuned them for low-RAM hosts (RAM is shared with
the rest of the stack).

## Files

| File | Mount target | Purpose |
|------|--------------|---------|
| `clickhouse/ipv4-only.xml` | `/etc/clickhouse-server/config.d/ipv4-only.xml:ro` | Restrict ClickHouse listen-host to `0.0.0.0` (IPv4 only) |
| `clickhouse/logs.xml` | `/etc/clickhouse-server/config.d/logs.xml:ro` | Disable most internal logs; keep `query_log` with 30-day TTL |
| `clickhouse/low-resources.xml` | `/etc/clickhouse-server/config.d/low-resources.xml:ro` | Cap `mark_cache_size` at 500 MB for low-RAM hosts |
| `clickhouse/default-profile-low-resources-overrides.xml` | `/etc/clickhouse-server/users.d/default-profile-low-resources-overrides.xml:ro` | Single-thread default profile; disable parallel parsing and formatting |

## Provenance

All four files are copied verbatim from the upstream `plausible/community-edition` repository
at tag `v3.2.0`:

<https://github.com/plausible/community-edition/tree/v3.2.0/clickhouse>

**On upgrade:** when bumping the Plausible CE pin in `deploy/docker-compose.prod.yml`,
re-fetch all four files at the new upstream tag and DIFF before committing. Silent upstream
tuning changes can materially affect ClickHouse memory and threading behavior, and a stale
local copy paired with a newer ClickHouse image is a known foot-gun.

## Operator workflow

For the full first-time setup (DNS, secrets, deploy, first-admin bootstrap, smoke
verification, daily ops, licensing), see `../RUNBOOK-plausible.md`.

**DO NOT hand-edit the XML files.** Re-fetch from upstream on upgrade.
