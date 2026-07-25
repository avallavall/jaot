"""Move the AI assistant onto Claude Sonnet 5 / Opus 5.

Data-only migration. The models live in ``platform_settings``, and
``PlatformSettingsService.get`` prefers the DB row over the registry default,
so editing the registry alone never reaches an existing install (the 20260327
seed runs ON CONFLICT DO NOTHING, and the boot-time self-heal only refreshes
*readonly* settings). Same reason the 20260629 limit relax needed a migration.

Changes (new <- old):
  - LLM_DEFAULT_MODEL:   claude-sonnet-5 <- claude-sonnet-4-6
  - LLM_ADVANCED_MODEL:  claude-opus-5   <- claude-opus-4-6
  - LLM_MODEL_PRICING_EUR_PER_MTOK: adds claude-sonnet-5, claude-opus-5 and
    claude-fable-5 entries.
  - LLM_THINKING_EFFORT: seeded at "high" (replaces the now-unused
    LLM_THINKING_BUDGET_TOKENS, which is left in place — additive-only).

It also widens ``platform_settings.value`` and ``.description`` from
VARCHAR(500) to TEXT. The pricing map reached 468 of its 500 characters with
these three entries — the next model added would have failed the seed on fresh
installs — and the accompanying description no longer fitted at all. Widening a
varchar is a metadata-only operation in PostgreSQL (no table rewrite, no lock
held over the data) and is additive: the old code reads a wider column happily,
so an image rollback needs no schema change. The downgrade therefore does NOT
narrow it back — that would truncate real data.

Two deliberate choices:

- The model updates are **conditional on the old value**. An operator who
  deliberately pinned a different model keeps it; re-running the migration is
  a no-op. A blind UPDATE would silently overwrite that choice.
- The pricing update **merges keys** instead of replacing the blob, so local
  edits to existing rates survive. Without the new entries these models would
  fall through to ``default`` (Opus rates), which under-prices Fable 5 by
  roughly half and would quietly skew the monthly EUR budget guardrail.

Revision ID: 20260725_llm_models_v5
Revises: 20260720_llmconv_ledger_uq
Create Date: 2026-07-25
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "20260725_llm_models_v5"
down_revision = "20260720_llmconv_ledger_uq"
branch_labels = None
depends_on = None

_UPDATED_BY = "llm_models_v5"

# (key, new_value, old_value) — applied only when the row still holds the
# other side of the pair.
_MODEL_CHANGES: list[tuple[str, str, str]] = [
    ("LLM_DEFAULT_MODEL", "claude-sonnet-5", "claude-sonnet-4-6"),
    ("LLM_ADVANCED_MODEL", "claude-opus-5", "claude-opus-4-6"),
]

_PRICING_KEY = "LLM_MODEL_PRICING_EUR_PER_MTOK"

# Anthropic USD list prices converted at ~1.08 USD/EUR, matching the registry.
_NEW_PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 2.78, "output": 13.89},
    "claude-opus-5": {"input": 4.63, "output": 23.15},
    "claude-fable-5": {"input": 9.26, "output": 46.30},
}

_EFFORT_KEY = "LLM_THINKING_EFFORT"
_EFFORT_VALUE = "high"
_EFFORT_DESC = (
    "Reasoning depth for the advanced model's adaptive thinking, and the "
    "replacement for LLM_THINKING_BUDGET_TOKENS. One of: low, medium, high, "
    "xhigh, max."
)


def _swap_models(changes: list[tuple[str, str, str]]) -> None:
    """Apply (key, new, old) updates, but only where the row holds the old value."""
    conn = op.get_bind()
    for key, new_value, old_value in changes:
        conn.execute(
            text(
                "UPDATE platform_settings"
                " SET value = :new_value, updated_at = NOW(), updated_by = :updated_by"
                " WHERE key = :key AND value = :old_value"
            ),
            {
                "key": key,
                "new_value": new_value,
                "old_value": old_value,
                "updated_by": _UPDATED_BY,
            },
        )


def _merge_pricing(add: dict[str, dict[str, float]], remove: list[str]) -> None:
    """Add/remove pricing entries without clobbering unrelated local edits."""
    conn = op.get_bind()
    row = conn.execute(
        text("SELECT value FROM platform_settings WHERE key = :key"),
        {"key": _PRICING_KEY},
    ).first()
    if row is None:
        # Not seeded yet — the boot-time self-heal inserts the registry default,
        # which already carries these entries.
        return

    try:
        prices = json.loads(row[0])
    except (TypeError, ValueError):
        # Hand-edited into something unparseable: leave it alone rather than
        # destroying the operator's value. Cost tracking falls back to
        # "default" rates until it is fixed.
        return
    if not isinstance(prices, dict):
        return

    changed = False
    for model, rates in add.items():
        if model not in prices:
            prices[model] = rates
            changed = True
    for model in remove:
        if prices.pop(model, None) is not None:
            changed = True
    if not changed:
        return

    conn.execute(
        text(
            "UPDATE platform_settings"
            " SET value = :value, updated_at = NOW(), updated_by = :updated_by"
            " WHERE key = :key"
        ),
        {
            "key": _PRICING_KEY,
            "value": json.dumps(prices),
            "updated_by": _UPDATED_BY,
        },
    )


def upgrade() -> None:
    # Must run before the writes below — the new pricing description exceeds 500.
    op.alter_column(
        "platform_settings",
        "value",
        type_=sa.Text(),
        existing_type=sa.String(500),
        existing_nullable=False,
    )
    op.alter_column(
        "platform_settings",
        "description",
        type_=sa.Text(),
        existing_type=sa.String(500),
        existing_nullable=True,
    )

    _swap_models(_MODEL_CHANGES)
    _merge_pricing(add=_NEW_PRICES, remove=[])

    conn = op.get_bind()
    conn.execute(
        text(
            "INSERT INTO platform_settings"
            " (key, value, description, updated_at, updated_by)"
            " VALUES (:key, :value, :desc, NOW(), :updated_by)"
            " ON CONFLICT (key) DO NOTHING"
        ),
        {
            "key": _EFFORT_KEY,
            "value": _EFFORT_VALUE,
            "desc": _EFFORT_DESC,
            "updated_by": _UPDATED_BY,
        },
    )


def downgrade() -> None:
    # NOTE: the TEXT widening is deliberately not reverted — narrowing back to
    # VARCHAR(500) would fail (or truncate) on any row that has since grown.
    # Mirror image: swap back only where the row still holds the new value.
    _swap_models([(key, old, new) for key, new, old in _MODEL_CHANGES])
    _merge_pricing(add={}, remove=list(_NEW_PRICES))

    conn = op.get_bind()
    conn.execute(
        text("DELETE FROM platform_settings WHERE key = :key AND updated_by = :updated_by"),
        {"key": _EFFORT_KEY, "updated_by": _UPDATED_BY},
    )
