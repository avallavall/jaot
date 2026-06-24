"""
Expression Parser for Optimization Problems

Recursive descent parser that converts mathematical expressions into
SCIP-compatible linear/quadratic expressions.

Supports:
- Linear terms: 3*x, -2*y, x
- Quadratic terms: x*y, 2*x*x, x^2, x**2
- Comparison operators: <=, >=, ==, <, >
- Parenthesized grouping with arbitrary nesting: (x + y) * 2, ((a + b) * (c - d))
- Exponentiation: ^ and ** operators
- Built-in functions: abs(), min(), max(), sum(), pow()
- Standard math operators: +, -, *, /
- Clear error messages with position indicators and error codes

Grammar:
    expression  -> term (('+' | '-') term)*
    term        -> factor (('*' | '/') factor)*
    factor      -> base (('^' | '**') factor)?      # right-associative
    base        -> NUMBER | VARIABLE | function_call | '(' expression ')' | ('+' | '-') base
    function_call -> FUNCTION_NAME '(' expr_list ')'
    expr_list   -> expression (',' expression)*
"""

import re
from dataclasses import dataclass


@dataclass
class Term:
    """A single term in an expression (coefficient * variable(s))."""

    coefficient: float
    variables: list[str]  # Empty for constant, one for linear, two for quadratic


@dataclass
class ParsedExpression:
    """Result of parsing an expression."""

    terms: list[Term]
    constant: float = 0.0

    def is_linear(self) -> bool:
        """Check if expression is linear (no quadratic terms)."""
        return all(len(t.variables) <= 1 for t in self.terms)


@dataclass
class ParsedConstraint:
    """Result of parsing a constraint expression."""

    lhs: ParsedExpression  # Left-hand side
    operator: str  # <=, >=, ==
    rhs: float  # Right-hand side (constant)


class ParseError(ValueError):
    """
    Structured parse error with position information and error code.

    Formats error messages with a pointer arrow like Python syntax errors:

        EXPR_PARSE_ERROR: Unexpected token ')' at position 7
          (x + y)) * 2
                ^
    """

    def __init__(
        self,
        message: str,
        position: int = -1,
        expression: str = "",
        error_code: str = "EXPR_PARSE_ERROR",
    ):
        self.error_message = message
        self.position = position
        self.expression = expression
        self.error_code = error_code
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = [f"{self.error_code}: {self.error_message}"]
        if self.expression and self.position >= 0:
            lines.append(f"  {self.expression}")
            lines.append(f"  {' ' * self.position}^")
        return "\n".join(lines)


# Token type constants
_TT_NUMBER = "NUMBER"
_TT_VARIABLE = "VARIABLE"
_TT_FUNCTION = "FUNCTION"
_TT_PLUS = "PLUS"
_TT_MINUS = "MINUS"
_TT_STAR = "STAR"
_TT_SLASH = "SLASH"
_TT_POWER = "POWER"
_TT_LPAREN = "LPAREN"
_TT_RPAREN = "RPAREN"
_TT_COMMA = "COMMA"
_TT_EOF = "EOF"

# Built-in function names
BUILTIN_FUNCTIONS = {"min", "max", "abs", "sum", "pow"}


@dataclass
class Token:
    """A token with type, value, and position in the original string."""

    type: str
    value: str
    pos: int  # Start position in original expression


def _tokenize(expr: str) -> list[Token]:
    """
    Tokenize an expression string into a list of typed tokens.

    Handles numbers, variables, function names, operators (+, -, *, /, ^, **),
    parentheses, and commas.
    """
    tokens: list[Token] = []
    i = 0
    length = len(expr)

    while i < length:
        ch = expr[i]

        # Skip whitespace
        if ch == " " or ch == "\t":
            i += 1
            continue

        # Number (integer or float)
        if ch.isdigit() or (ch == "." and i + 1 < length and expr[i + 1].isdigit()):
            start = i
            while i < length and (expr[i].isdigit() or expr[i] == "."):
                i += 1
            tokens.append(Token(_TT_NUMBER, expr[start:i], start))
            continue

        # Identifier (variable or function name)
        if ch.isalpha() or ch == "_":
            start = i
            while i < length and (expr[i].isalnum() or expr[i] == "_"):
                i += 1
            name = expr[start:i]
            # Check if it's a built-in function (followed by '(')
            peek = i
            while peek < length and expr[peek] == " ":
                peek += 1
            if name in BUILTIN_FUNCTIONS and peek < length and expr[peek] == "(":
                tokens.append(Token(_TT_FUNCTION, name, start))
            else:
                tokens.append(Token(_TT_VARIABLE, name, start))
            continue

        # Two-character operators
        if ch == "*" and i + 1 < length and expr[i + 1] == "*":
            tokens.append(Token(_TT_POWER, "**", i))
            i += 2
            continue

        # Single-character operators and delimiters
        if ch == "+":
            tokens.append(Token(_TT_PLUS, "+", i))
            i += 1
            continue
        if ch == "-":
            tokens.append(Token(_TT_MINUS, "-", i))
            i += 1
            continue
        if ch == "*":
            tokens.append(Token(_TT_STAR, "*", i))
            i += 1
            continue
        if ch == "/":
            tokens.append(Token(_TT_SLASH, "/", i))
            i += 1
            continue
        if ch == "^":
            tokens.append(Token(_TT_POWER, "^", i))
            i += 1
            continue
        if ch == "(":
            tokens.append(Token(_TT_LPAREN, "(", i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token(_TT_RPAREN, ")", i))
            i += 1
            continue
        if ch == ",":
            tokens.append(Token(_TT_COMMA, ",", i))
            i += 1
            continue

        # Unknown character
        raise ParseError(
            f"Unexpected character '{ch}' at position {i}",
            position=i,
            expression=expr,
        )

    tokens.append(Token(_TT_EOF, "", length))
    return tokens


class _ExpressionAST:
    """
    Internal recursive descent parser that builds a flat list of (coefficient, variables)
    pairs from an expression token stream.

    The parser evaluates the expression eagerly: it distributes multiplication,
    computes constants, and produces a final list of Term objects plus a constant.
    """

    MAX_NESTING_DEPTH = 200

    def __init__(self, tokens: list[Token], expression: str):
        self._tokens = tokens
        self._pos = 0
        self._expression = expression
        self._depth = 0

    def _current(self) -> Token:
        return self._tokens[self._pos]

    def _peek_type(self) -> str:
        return self._tokens[self._pos].type

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, ttype: str) -> Token:
        tok = self._current()
        if tok.type != ttype:
            raise ParseError(
                f"Expected {ttype} but got '{tok.value}' at position {tok.pos}",
                position=tok.pos,
                expression=self._expression,
            )
        return self._advance()

    # Core representation: a "value" is (terms: List[Tuple[float, List[str]]], constant: float)
    # This allows distributing multiplication across sub-expressions.

    def parse(self) -> tuple[list[Term], float]:
        """Parse the full expression and return (terms, constant)."""
        terms_raw, const = self._parse_expression()
        # At top level, only EOF is acceptable — RPAREN and COMMA are errors
        tok = self._current()
        if tok.type != _TT_EOF:
            if tok.type == _TT_RPAREN:
                raise ParseError(
                    f"Unmatched closing parenthesis at position {tok.pos}",
                    position=tok.pos,
                    expression=self._expression,
                )
            raise ParseError(
                f"Unexpected token '{tok.value}' at position {tok.pos}",
                position=tok.pos,
                expression=self._expression,
            )
        terms = [Term(coefficient=c, variables=list(v)) for c, v in terms_raw]
        return terms, const

    # Grammar methods — each returns (List[Tuple[float, Tuple[str,...]]], float)

    def _parse_expression(self) -> tuple[list[tuple[float, tuple[str, ...]]], float]:
        """expression -> term (('+' | '-') term)*"""
        terms, const = self._parse_term()

        while self._peek_type() in (_TT_PLUS, _TT_MINUS):
            if self._peek_type() == _TT_PLUS:
                self._advance()
                t2, c2 = self._parse_term()
                terms.extend(t2)
                const += c2
            else:  # MINUS
                self._advance()
                t2, c2 = self._parse_term()
                terms.extend((-coef, vs) for coef, vs in t2)
                const -= c2

        return terms, const

    def _parse_term(self) -> tuple[list[tuple[float, tuple[str, ...]]], float]:
        """term -> factor (('*' | '/') factor)*"""
        terms, const = self._parse_factor()

        while self._peek_type() in (_TT_STAR, _TT_SLASH):
            op = self._advance()
            right_terms, right_const = self._parse_factor()

            if op.type == _TT_SLASH:
                # Division: right side must be a pure constant
                if right_terms:
                    raise ParseError(
                        "Division by a variable expression is not supported in linear/quadratic "
                        "programming",
                        position=op.pos,
                        expression=self._expression,
                    )
                if abs(right_const) < 1e-15:
                    raise ParseError(
                        "Division by zero",
                        position=op.pos,
                        expression=self._expression,
                    )
                inv = 1.0 / right_const
                terms = [(c * inv, vs) for c, vs in terms]
                const *= inv
            else:
                # Multiplication: distribute (terms + const) * (right_terms + right_const)
                terms, const = self._multiply(terms, const, right_terms, right_const)

        return terms, const

    def _parse_factor(self) -> tuple[list[tuple[float, tuple[str, ...]]], float]:
        """factor -> base (('^' | '**') factor)?   # right-associative"""
        terms, const = self._parse_base()

        if self._peek_type() == _TT_POWER:
            self._advance()
            # Right-associative: parse factor recursively
            exp_terms, exp_const = self._parse_factor()
            if exp_terms:
                raise ParseError(
                    "Exponent must be a constant, not a variable expression",
                    position=self._current().pos,
                    expression=self._expression,
                )
            exponent = int(exp_const)
            if abs(exponent - exp_const) > 1e-9 or exponent < 0:
                raise ParseError(
                    "Only non-negative integer exponents are supported",
                    position=self._current().pos,
                    expression=self._expression,
                )
            terms, const = self._exponentiate(terms, const, exponent)

        return terms, const

    def _parse_base(self) -> tuple[list[tuple[float, tuple[str, ...]]], float]:
        """base -> NUMBER | VARIABLE | function_call | '(' expression ')' | ('+' | '-') base"""
        tok = self._current()

        # Unary plus/minus
        if tok.type == _TT_PLUS:
            self._advance()
            return self._parse_base()
        if tok.type == _TT_MINUS:
            self._advance()
            terms, const = self._parse_base()
            return [(-c, vs) for c, vs in terms], -const

        # Number
        if tok.type == _TT_NUMBER:
            self._advance()
            return [], float(tok.value)

        # Function call
        if tok.type == _TT_FUNCTION:
            return self._parse_function_call()

        # Variable
        if tok.type == _TT_VARIABLE:
            self._advance()
            return [(1.0, (tok.value,))], 0.0

        # Parenthesized expression
        if tok.type == _TT_LPAREN:
            self._depth += 1
            if self._depth > self.MAX_NESTING_DEPTH:
                raise ParseError(
                    f"Expression exceeds maximum nesting depth of {self.MAX_NESTING_DEPTH}",
                    position=tok.pos,
                    expression=self._expression,
                )
            self._advance()
            terms, const = self._parse_expression()
            self._expect(_TT_RPAREN)
            self._depth -= 1
            return terms, const

        # Unexpected token
        if tok.type == _TT_RPAREN:
            raise ParseError(
                f"Unmatched closing parenthesis at position {tok.pos}",
                position=tok.pos,
                expression=self._expression,
            )
        if tok.type == _TT_EOF:
            raise ParseError(
                "Unexpected end of expression",
                position=tok.pos,
                expression=self._expression,
            )

        raise ParseError(
            f"Unexpected token '{tok.value}' at position {tok.pos}",
            position=tok.pos,
            expression=self._expression,
        )

    def _parse_function_call(self) -> tuple[list[tuple[float, tuple[str, ...]]], float]:
        """function_call -> FUNCTION_NAME '(' expr_list ')'"""
        func_tok = self._advance()  # consume function name
        func_name = func_tok.value

        self._expect(_TT_LPAREN)

        args: list[tuple[list[tuple[float, tuple[str, ...]]], float]] = []
        if self._peek_type() != _TT_RPAREN:
            args.append(self._parse_expression())
            while self._peek_type() == _TT_COMMA:
                self._advance()
                args.append(self._parse_expression())

        self._expect(_TT_RPAREN)

        return self._evaluate_function(func_name, args, func_tok.pos)

    def _evaluate_function(
        self,
        name: str,
        args: list[tuple[list[tuple[float, tuple[str, ...]]], float]],
        pos: int,
    ) -> tuple[list[tuple[float, tuple[str, ...]]], float]:
        """Evaluate a built-in function on its parsed arguments."""
        if name == "sum":
            # sum(a, b, c) = a + b + c  (syntactic sugar)
            all_terms: list[tuple[float, tuple[str, ...]]] = []
            total_const = 0.0
            for terms, const in args:
                all_terms.extend(terms)
                total_const += const
            return all_terms, total_const

        if name == "pow":
            if len(args) != 2:
                raise ParseError(
                    f"pow() requires exactly 2 arguments, got {len(args)}",
                    position=pos,
                    expression=self._expression,
                )
            base_terms, base_const = args[0]
            exp_terms, exp_const = args[1]
            if exp_terms:
                raise ParseError(
                    "pow() exponent must be a constant",
                    position=pos,
                    expression=self._expression,
                )
            exponent = int(exp_const)
            if abs(exponent - exp_const) > 1e-9 or exponent < 0:
                raise ParseError(
                    "Only non-negative integer exponents are supported in pow()",
                    position=pos,
                    expression=self._expression,
                )
            return self._exponentiate(base_terms, base_const, exponent)

        if name == "abs":
            if len(args) != 1:
                raise ParseError(
                    f"abs() requires exactly 1 argument, got {len(args)}",
                    position=pos,
                    expression=self._expression,
                )
            terms, const = args[0]
            if terms:
                raise ParseError(
                    "abs() of a variable expression is not supported in linear programming. "
                    "Use auxiliary variables and constraints instead.",
                    position=pos,
                    expression=self._expression,
                )
            return [], abs(const)

        if name in ("min", "max"):
            all_const = all(not terms for terms, const in args)
            if not all_const:
                raise ParseError(
                    f"{name}() of variable expressions is not supported in linear programming. "
                    "Use auxiliary variables and constraints instead.",
                    position=pos,
                    expression=self._expression,
                )
            values = [const for _, const in args]
            result = min(values) if name == "min" else max(values)
            return [], result

        raise ParseError(
            f"Unknown function '{name}'",
            position=pos,
            expression=self._expression,
        )

    @staticmethod
    def _multiply(
        left_terms: list[tuple[float, tuple[str, ...]]],
        left_const: float,
        right_terms: list[tuple[float, tuple[str, ...]]],
        right_const: float,
    ) -> tuple[list[tuple[float, tuple[str, ...]]], float]:
        """
        Distribute multiplication of two sub-expressions:
        (left_terms + left_const) * (right_terms + right_const)
        """
        result_terms: list[tuple[float, tuple[str, ...]]] = []
        result_const = left_const * right_const

        # left_const * right_terms
        for c, vs in right_terms:
            result_terms.append((left_const * c, vs))

        # left_terms * right_const
        for c, vs in left_terms:
            result_terms.append((c * right_const, vs))

        # left_terms * right_terms (cross product)
        for c1, v1 in left_terms:
            for c2, v2 in right_terms:
                combined = tuple(sorted(v1 + v2))
                result_terms.append((c1 * c2, combined))

        return result_terms, result_const

    def _exponentiate(
        self,
        terms: list[tuple[float, tuple[str, ...]]],
        const: float,
        exponent: int,
    ) -> tuple[list[tuple[float, tuple[str, ...]]], float]:
        """Raise (terms + const) to an integer power via repeated multiplication."""
        if exponent == 0:
            return [], 1.0
        if exponent == 1:
            return terms, const

        result_terms = terms
        result_const = const
        for _ in range(exponent - 1):
            result_terms, result_const = self._multiply(result_terms, result_const, terms, const)
            # Check for terms with more than 2 variables (beyond quadratic)
            for _, vs in result_terms:
                if len(vs) > 2:
                    raise ParseError(
                        "Expressions of degree > 2 are not supported (only linear and "
                        "quadratic terms are allowed)",
                        position=0,
                        expression=self._expression,
                    )

        return result_terms, result_const


class ExpressionParser:
    """
    Parser for mathematical expressions used in optimization problems.

    Uses recursive descent parsing to handle:
    - Operator precedence: +/- < */divide < ^ < unary < parentheses
    - Parenthesized grouping: (x + y) * 2
    - Exponentiation: x^2, x**2
    - Built-in functions: abs(), min(), max(), sum(), pow()
    - Position-aware error messages with EXPR_PARSE_ERROR codes

    Usage:
        parser = ExpressionParser()

        expr = parser.parse_expression("(x + y) * 2 - 5")

        constraint = parser.parse_constraint("x + 2*y <= 10")
    """

    # Regex for comparison operators (used by parse_constraint)
    COMPARISON_PATTERN = re.compile(r"(<=|>=|==|<|>)")

    def __init__(self) -> None:
        self._variable_names: set[str] = set()

    def parse_expression(
        self,
        expr_str: str,
        known_variables: list[str] | None = None,
    ) -> ParsedExpression:
        """
        Parse a mathematical expression into terms.

        Args:
            expr_str: Expression string like "3*x + 2*y - 5" or "(x + y) * 2"
            known_variables: List of valid variable names

        Returns:
            ParsedExpression with terms and constant

        Raises:
            ParseError (subclass of ValueError): If the expression is malformed
        """
        if known_variables:
            self._variable_names = set(known_variables)

        # Normalize: handle implicit multiplication (2x -> 2*x)
        normalized = self._normalize(expr_str)

        # Tokenize
        tokens = _tokenize(normalized)

        parser = _ExpressionAST(tokens, normalized)
        terms, constant = parser.parse()

        # Consolidate duplicate terms
        terms, constant = self._consolidate(terms, constant)

        return ParsedExpression(terms=terms, constant=constant)

    def parse_constraint(
        self,
        constraint_str: str,
        known_variables: list[str] | None = None,
    ) -> ParsedConstraint:
        """
        Parse a constraint expression.

        Args:
            constraint_str: Constraint like "x + 2*y <= 10" or "(x + y) * 2 >= 5"
            known_variables: List of valid variable names

        Returns:
            ParsedConstraint with lhs, operator, and rhs
        """
        match = self.COMPARISON_PATTERN.search(constraint_str)
        if not match:
            raise ParseError(
                f"No comparison operator found in: {constraint_str}",
                expression=constraint_str,
            )

        operator = match.group(1)
        lhs_str, rhs_str = constraint_str.split(operator, 1)

        lhs = self.parse_expression(lhs_str.strip(), known_variables)
        rhs = self.parse_expression(rhs_str.strip(), known_variables)

        # Move all variable terms to LHS, constants to RHS
        for term in rhs.terms:
            lhs.terms.append(
                Term(
                    coefficient=-term.coefficient,
                    variables=term.variables,
                )
            )

        rhs_value = rhs.constant - lhs.constant
        lhs.constant = 0.0

        return ParsedConstraint(lhs=lhs, operator=operator, rhs=rhs_value)

    @staticmethod
    def _normalize(expr: str) -> str:
        """
        Normalize expression string.

        - Handles implicit multiplication: 2x -> 2*x  (only at word boundaries)
        - Preserves whitespace (tokenizer handles stripping)
        """
        # Handle implicit multiplication: digit followed by letter/paren, but only
        # when the digit is NOT inside a variable name (preceded by letter/underscore).
        # e.g., "2x" -> "2*x" but "x_0_c" stays unchanged.
        expr = re.sub(r"(?<![a-zA-Z_])(\d)([a-zA-Z(])", r"\1*\2", expr)
        # Handle implicit multiplication: ) followed by letter/digit/(
        expr = re.sub(r"\)([a-zA-Z0-9_(])", r")*\1", expr)
        return expr

    @staticmethod
    def _consolidate(
        terms: list[Term],
        constant: float,
    ) -> tuple[list[Term], float]:
        """
        Consolidate terms with the same variable set and remove zero-coefficient terms.
        """
        term_map: dict[tuple[str, ...], float] = {}
        for term in terms:
            key = tuple(sorted(term.variables))
            if not key:
                constant += term.coefficient
            else:
                term_map[key] = term_map.get(key, 0.0) + term.coefficient

        result = []
        for vars_tuple, coef in term_map.items():
            if abs(coef) > 1e-15:
                result.append(Term(coefficient=coef, variables=list(vars_tuple)))

        return result, constant
