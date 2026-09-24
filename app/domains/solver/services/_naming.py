"""Shared naming utilities for solver services.

Variable and constraint names from external files (MPS, LP, CIP) may contain
characters that violate JAOT's identifier rules.  This module provides a single
canonical sanitizer so every entry-point (file import, CIP fallback, template
engine) produces consistent names.
"""

import re


def sanitize_var_name(name: str) -> str:
    """Sanitize a name to JAOT's ``[a-zA-Z_][a-zA-Z0-9_]*`` rule.

    * Non-alphanumeric characters (except ``_``) become ``_``.
    * A leading digit gets a ``v_`` prefix.
    * Case is preserved (generators may lowercase separately).
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"v_{sanitized}"
    return sanitized


def constraint_label(name: str | None, index: int) -> str:
    """The name a row goes by: its own, or ``c1``, ``c2``... by position.

    One rule for every consumer. The adapters and the infeasibility diagnosis
    counted from ``c0`` while the exact analysis, the what-if analysis and the
    builder counted from ``c1``, so SCIP's binding flags for unnamed rows were
    each read from the row before, and the reduced-cost derivation found no
    price for any unnamed row and fell back to the double-counted one.
    """
    return name or f"c{index + 1}"
