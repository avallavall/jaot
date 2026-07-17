"""JModel DSL bounded context.

A lean, declarative, AMPL/ZIMPL-flavored modeling language that lowers
deterministically to the flat :class:`~app.schemas.optimization.OptimizationProblem`.
It is an index-algebra macro expander — sets / params / indexed variable & constraint
families / ``sum{}`` / set-filters — NOT a math core: every scalar leaf is emitted as a
plain expression string that the existing ``ExpressionParser`` (solve path) parses
verbatim. Turing-incomplete by design and statically analyzable.

Grammar is frozen in ``.claude/plans/jmodel-grammar-2026-07-01.md``; the §8 Scenarios
extension adds declaration-only ``set I;`` / ``param w{I};`` statements whose values
come from a :class:`JModelData` dataset passed to :func:`compile_jmodel`.

This domain imports ONLY ``app.schemas`` — never ``app.domains.solver`` — to stay within
the ``domains-independent`` import-linter contract.
"""

from app.domains.dsl.compiler import (
    JModelData,
    JModelError,
    ModelDeclarations,
    ParamInfo,
    SetInfo,
    compile_jmodel,
    inspect_declarations,
)

__all__ = [
    "JModelData",
    "JModelError",
    "ModelDeclarations",
    "ParamInfo",
    "SetInfo",
    "compile_jmodel",
    "inspect_declarations",
]
