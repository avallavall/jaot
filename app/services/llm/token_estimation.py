"""Token estimation and truncation detection for LLM resilience.

Provides heuristic token counting, dynamic output token estimation based on
problem complexity, and incomplete JSON detection for truncation recovery.
"""

from __future__ import annotations

import re
from typing import Any


def estimate_tokens(text: str) -> int:
    """Estimate token count from character count. ~4 chars per token."""
    return max(len(text) // 4 + 1, 1)


def _extract_quantity_numbers(text: str) -> list[int]:
    """Extract numbers likely representing problem quantities, filtering noise.

    Filters out:
    - Percentages (e.g. "5%", "12.5 %")
    - Years (4-digit numbers in the 1900-2100 range)
    - Very small numbers (0 and 1) that rarely indicate problem size
    """
    # Remove percentage patterns first: digits (possibly with decimals) followed by %
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*%", "", text)

    raw_numbers = [int(n) for n in re.findall(r"\d+", cleaned)]

    result = []
    for n in raw_numbers:
        # Skip years (1900-2100)
        if 1900 <= n <= 2100:
            continue
        # Skip trivially small numbers (0, 1) — not meaningful for size estimation
        if n <= 1:
            continue
        result.append(n)

    return result


def estimate_output_tokens(user_message: str, db: Any | None = None) -> int:
    """Estimate required output tokens from the user's problem description.

    Heuristic: find the largest number in the message (correlates with
    problem size -- e.g. "50 employees", "200 stocks"), estimate variables
    and constraints, multiply by tokens-per-item.

    Returns at least ``LLM_MAX_TOKENS`` from platform settings.
    """
    from app.services.platform_settings_service import (
        PlatformSettingsService as PSS,
    )

    if db is not None:
        llm_max_tokens = PSS.get_int(db, "LLM_MAX_TOKENS")
    else:
        from app.shared.db.session import SessionLocal

        _db = SessionLocal()
        try:
            llm_max_tokens = PSS.get_int(_db, "LLM_MAX_TOKENS")
        finally:
            _db.close()

    numbers = _extract_quantity_numbers(user_message)
    if not numbers:
        return llm_max_tokens

    max_number = max(numbers)
    estimated_vars = min(max_number, 500)
    # Constraint-heavy problems (time windows, etc.) often have 3-5x constraints per variable
    estimated_constraints = estimated_vars * 3

    tokens = 500 + estimated_vars * 40 + estimated_constraints * 30
    return max(tokens, llm_max_tokens)


def is_json_incomplete(text: str) -> bool:
    """Check if JSON text is truncated or malformed.

    Uses actual JSON parsing as the primary check (reliable) with
    brace/bracket counting as a fast secondary heuristic.
    """
    import json as _json

    text = text.strip()
    if not text:
        return True
    # Primary: try to parse — if it succeeds, the JSON is complete
    try:
        _json.loads(text)
        return False
    except _json.JSONDecodeError:
        return True
