"""JModel DSL bounded context.

A lean, declarative, AMPL/ZIMPL-flavored modeling language that lowers
deterministically to the flat :class:`~app.schemas.optimization.OptimizationProblem`.
It is an index-algebra macro expander — sets / params / indexed variable & constraint
families / ``sum{}`` / set-filters — NOT a math core: every scalar leaf is emitted as a
plain expression string that the existing ``ExpressionParser`` (solve path) parses
verbatim. Turing-incomplete by design and statically analyzable.

Grammar is frozen in ``.claude/plans/jmodel-grammar-2026-07-01.md``.

This domain imports ONLY ``app.schemas`` — never ``app.domains.solver`` — to stay within
the ``domains-independent`` import-linter contract.
"""

from app.domains.dsl.compiler import JModelError, compile_jmodel

__all__ = ["JModelError", "compile_jmodel"]
