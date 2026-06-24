"""Verify expression_parser imports without pyscipopt installed.

TD-3 resolution test per SOLV-06 / D-08.
Phase 4 deletes the module-level `from pyscipopt import Variable as SCIPVariable`
at expression_parser.py:30 and moves build_scip_expression() to SCIPAdapter.
After that change, this test must pass even with pyscipopt simulated as missing.
"""

import importlib
import sys

import pytest


@pytest.mark.unit
def test_expression_parser_imports_without_pyscipopt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """expression_parser must not import pyscipopt at module level."""
    # CRITICAL: Pop BOTH modules BEFORE patching. If expression_parser is
    # already cached from test collection, the import machinery will return
    # the cached module and never re-execute the module body — which means
    # the patched sys.modules has no effect. See Research §Pitfall 5.
    parser_mod = "app.domains.solver.services.expression_parser"

    # Test-order coupling fix (2026-05-21): re-importing expression_parser
    # below replaces the cached module with a fresh object — and crucially a
    # fresh `ParseError` class. tests/test_expression_parser.py binds
    # ExpressionParser (and transitively the ORIGINAL ParseError) at its
    # module top level during collection. If this test runs FIRST under
    # pytest-randomly, the leaked fresh module makes the later
    # `from ...expression_parser import ParseError` resolve to a DIFFERENT
    # class than the one the parser instance actually raises, so
    # `pytest.raises(ParseError)` fails to catch it (test_max/min_function).
    # Register the original module with monkeypatch so it is restored on
    # teardown, returning sys.modules to its pre-test state.
    original_parser_mod = sys.modules.get(parser_mod)
    if original_parser_mod is not None:
        monkeypatch.setitem(sys.modules, parser_mod, original_parser_mod)

    sys.modules.pop(parser_mod, None)
    sys.modules.pop("pyscipopt", None)

    # Setting to None causes the next `import pyscipopt` to raise
    # ModuleNotFoundError (subclass of ImportError).
    # Per https://docs.python.org/3/reference/import.html#the-module-cache
    monkeypatch.setitem(sys.modules, "pyscipopt", None)

    # The import must succeed cleanly — no ImportError, no ModuleNotFoundError.
    parser = importlib.import_module(parser_mod)

    # Sanity: the public API is still present.
    assert hasattr(parser, "ExpressionParser")
    assert hasattr(parser, "ParsedExpression")
    assert hasattr(parser, "Term")
    assert hasattr(parser, "ParsedConstraint")

    # build_scip_expression is GONE (moved to SCIPAdapter per D-05).
    assert not hasattr(parser, "build_scip_expression"), (
        "build_scip_expression must be removed from expression_parser.py "
        "and live in SCIPAdapter per D-05/D-06."
    )

    # The ExpressionParser class itself must not expose build_scip_expression.
    assert not hasattr(parser.ExpressionParser, "build_scip_expression"), (
        "ExpressionParser.build_scip_expression must be removed per D-05."
    )

    # Defensive: pyscipopt MUST NOT have been imported as a side effect.
    assert "pyscipopt" in sys.modules
    assert sys.modules["pyscipopt"] is None


@pytest.mark.unit
def test_expression_parser_module_has_no_pyscipopt_import_line() -> None:
    """Grep-level check: the source file must not contain `from pyscipopt`.

    This catches the case where someone moves the import inside a function
    but leaves a stray top-level reference. Plan 02 must delete line 30 of
    expression_parser.py verbatim.
    """
    from pathlib import Path

    source = Path("app/domains/solver/services/expression_parser.py").read_text()
    assert "from pyscipopt" not in source, (
        "expression_parser.py must not contain any `from pyscipopt` line (TD-3 / SOLV-06)."
    )
    assert "import pyscipopt" not in source, (
        "expression_parser.py must not contain any `import pyscipopt` line."
    )
