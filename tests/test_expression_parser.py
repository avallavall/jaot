"""
Tests for the recursive descent expression parser.

Tests parenthesized expressions, exponentiation operators, built-in math functions,
error messages with position indicators, and backward compatibility with the
original linear expression parser.

Run with: pytest tests/test_expression_parser.py -v
"""

import pytest

from app.domains.solver.services.expression_parser import ExpressionParser


class TestBackwardCompatibility:
    """Re-test all existing cases from TestExpressionParser in test_solver.py."""

    def setup_method(self):
        self.parser = ExpressionParser()

    def test_parse_simple_expression(self):
        """Test parsing a simple linear expression."""
        expr = self.parser.parse_expression("3*x + 2*y", ["x", "y"])
        assert len(expr.terms) == 2
        assert expr.constant == 0

    def test_parse_expression_with_constant(self):
        """Test parsing expression with constant term."""
        expr = self.parser.parse_expression("3*x + 5", ["x"])
        assert len(expr.terms) == 1
        assert expr.constant == 5

    def test_parse_negative_coefficient(self):
        """Test parsing expression with negative coefficient."""
        expr = self.parser.parse_expression("3*x - 2*y", ["x", "y"])
        assert len(expr.terms) == 2
        # Find y term and check it's negative
        y_terms = [t for t in expr.terms if "y" in t.variables]
        assert len(y_terms) == 1
        assert y_terms[0].coefficient == -2.0

    def test_parse_constraint_less_equal(self):
        """Test parsing <= constraint."""
        constraint = self.parser.parse_constraint("x + 2*y <= 10", ["x", "y"])
        assert constraint.operator == "<="
        assert constraint.rhs == 10

    def test_parse_constraint_greater_equal(self):
        """Test parsing >= constraint."""
        constraint = self.parser.parse_constraint("3*x >= 5", ["x"])
        assert constraint.operator == ">="
        assert constraint.rhs == 5

    def test_parse_constraint_equality(self):
        """Test parsing == constraint."""
        constraint = self.parser.parse_constraint("x + y == 100", ["x", "y"])
        assert constraint.operator == "=="
        assert constraint.rhs == 100

    def test_implicit_coefficient(self):
        """Test that bare variable names get coefficient 1."""
        expr = self.parser.parse_expression("x", ["x"])
        assert len(expr.terms) == 1
        assert expr.terms[0].coefficient == 1.0
        assert expr.terms[0].variables == ["x"]

    def test_constant_only(self):
        """Test parsing a constant-only expression."""
        expr = self.parser.parse_expression("42", [])
        assert len(expr.terms) == 0
        assert expr.constant == 42.0

    def test_is_linear(self):
        """Test the is_linear check on parsed expressions."""
        expr = self.parser.parse_expression("3*x + 2*y", ["x", "y"])
        assert expr.is_linear()


class TestParenthesizedExpressions:
    """Tests for parenthesized expression support."""

    def setup_method(self):
        self.parser = ExpressionParser()

    def test_simple_parens(self):
        """(x + y) * 2 should produce terms with coef=2 for x and y."""
        expr = self.parser.parse_expression("(x + y) * 2", ["x", "y"])
        # Should be equivalent to 2*x + 2*y
        x_terms = [t for t in expr.terms if "x" in t.variables]
        y_terms = [t for t in expr.terms if "y" in t.variables]
        assert len(x_terms) >= 1
        assert len(y_terms) >= 1
        x_coef = sum(t.coefficient for t in x_terms)
        y_coef = sum(t.coefficient for t in y_terms)
        assert abs(x_coef - 2.0) < 1e-9
        assert abs(y_coef - 2.0) < 1e-9

    def test_nested_parens(self):
        """((a + b) * (c - d)) parses as the 4 quadratic terms a*c - a*d + b*c - b*d."""
        expr = self.parser.parse_expression("((a + b) * (c - d))", ["a", "b", "c", "d"])
        # Build a map keyed by sorted variable pair so order in the term list is
        # not important.
        quad = {tuple(sorted(t.variables)): t.coefficient for t in expr.terms}
        assert len(quad) == 4
        assert quad[("a", "c")] == pytest.approx(1.0, abs=1e-9)
        assert quad[("a", "d")] == pytest.approx(-1.0, abs=1e-9)
        assert quad[("b", "c")] == pytest.approx(1.0, abs=1e-9)
        assert quad[("b", "d")] == pytest.approx(-1.0, abs=1e-9)
        assert expr.constant == pytest.approx(0.0, abs=1e-9)

    def test_parens_with_constant(self):
        """(x + 3) * 2 should produce term for x with coef=2, constant=6."""
        expr = self.parser.parse_expression("(x + 3) * 2", ["x"])
        x_terms = [t for t in expr.terms if "x" in t.variables]
        x_coef = sum(t.coefficient for t in x_terms)
        assert abs(x_coef - 2.0) < 1e-9
        assert abs(expr.constant - 6.0) < 1e-9

    def test_deeply_nested(self):
        """(((x))) should be the same as just x."""
        expr = self.parser.parse_expression("(((x)))", ["x"])
        assert len(expr.terms) == 1
        assert expr.terms[0].variables == ["x"]
        assert abs(expr.terms[0].coefficient - 1.0) < 1e-9

    def test_mixed_parens_and_terms(self):
        """x + (y + z) * 3 => x has coef=1, y and z have coef=3."""
        expr = self.parser.parse_expression("x + (y + z) * 3", ["x", "y", "z"])
        x_coef = sum(t.coefficient for t in expr.terms if "x" in t.variables)
        y_coef = sum(t.coefficient for t in expr.terms if "y" in t.variables)
        z_coef = sum(t.coefficient for t in expr.terms if "z" in t.variables)
        assert abs(x_coef - 1.0) < 1e-9
        assert abs(y_coef - 3.0) < 1e-9
        assert abs(z_coef - 3.0) < 1e-9

    def test_negative_before_parens(self):
        """-(x + y) => x and y have coef=-1."""
        expr = self.parser.parse_expression("-(x + y)", ["x", "y"])
        x_coef = sum(t.coefficient for t in expr.terms if "x" in t.variables)
        y_coef = sum(t.coefficient for t in expr.terms if "y" in t.variables)
        assert abs(x_coef - (-1.0)) < 1e-9
        assert abs(y_coef - (-1.0)) < 1e-9

    def test_unmatched_open_paren_raises(self):
        """(x + y should raise ValueError with position info."""
        with pytest.raises(ValueError, match=r"[Pp]aren|[Uu]nmatched|[Ee]xpect"):
            self.parser.parse_expression("(x + y", ["x", "y"])

    def test_unmatched_close_paren_raises(self):
        """x + y) should raise ValueError with position info."""
        with pytest.raises(ValueError, match=r"[Pp]aren|[Uu]nmatched|[Uu]nexpect"):
            self.parser.parse_expression("x + y)", ["x", "y"])

    def test_parens_factor_on_left(self):
        """2 * (x + y) should also work (factor on left of parens)."""
        expr = self.parser.parse_expression("2 * (x + y)", ["x", "y"])
        x_coef = sum(t.coefficient for t in expr.terms if "x" in t.variables)
        y_coef = sum(t.coefficient for t in expr.terms if "y" in t.variables)
        assert abs(x_coef - 2.0) < 1e-9
        assert abs(y_coef - 2.0) < 1e-9

    def test_parens_in_constraint(self):
        """Constraint with parens: (x + y) * 2 <= 10."""
        constraint = self.parser.parse_constraint("(x + y) * 2 <= 10", ["x", "y"])
        assert constraint.operator == "<="
        assert abs(constraint.rhs - 10.0) < 1e-9


class TestExponentiation:
    """Tests for exponentiation operators (^ and **)."""

    def setup_method(self):
        self.parser = ExpressionParser()

    def test_caret_operator(self):
        """x ^ 2 should be recognized as exponentiation (quadratic term)."""
        expr = self.parser.parse_expression("x ^ 2", ["x"])
        # x^2 means x*x, so should have a quadratic term
        quad_terms = [t for t in expr.terms if len(t.variables) == 2]
        assert len(quad_terms) >= 1
        # The variables should be ["x", "x"]
        assert quad_terms[0].variables == ["x", "x"]

    def test_double_star_operator(self):
        """x ** 2 should produce the same result as x ^ 2."""
        expr = self.parser.parse_expression("x ** 2", ["x"])
        quad_terms = [t for t in expr.terms if len(t.variables) == 2]
        assert len(quad_terms) >= 1
        assert quad_terms[0].variables == ["x", "x"]

    def test_exponent_in_expression(self):
        """2 * x ^ 2 + 3 * y should have a quadratic x term and linear y term."""
        expr = self.parser.parse_expression("2 * x ^ 2 + 3 * y", ["x", "y"])
        quad_terms = [t for t in expr.terms if len(t.variables) == 2]
        linear_terms = [t for t in expr.terms if len(t.variables) == 1 and "y" in t.variables]
        assert len(quad_terms) >= 1
        assert quad_terms[0].coefficient == 2.0
        assert len(linear_terms) >= 1
        assert linear_terms[0].coefficient == 3.0


class TestBuiltInFunctions:
    """Tests for built-in math function recognition."""

    def setup_method(self):
        self.parser = ExpressionParser()

    def test_abs_function(self):
        """abs(x) should be recognized as a function (not treated as variable name 'abs')."""
        # abs of a variable is not directly supported in LP — should raise a clear error
        # rather than silently treating 'abs' as a variable name
        with pytest.raises(ValueError, match=r"abs\(\)|not supported"):
            self.parser.parse_expression("abs(x)", ["x"])

    def test_abs_constant(self):
        """abs(-5) should evaluate to 5 (constant folding)."""
        expr = self.parser.parse_expression("abs(-5)", [])
        assert len(expr.terms) == 0
        assert abs(expr.constant - 5.0) < 1e-9

    def test_min_function(self):
        """min() of variable expressions raises ParseError (not supported in LP)."""
        from app.domains.solver.services.expression_parser import ParseError

        with pytest.raises(ParseError, match="min.*not supported"):
            self.parser.parse_expression("min(x, y)", ["x", "y"])

    def test_max_function(self):
        """max() of variable expressions raises ParseError (not supported in LP)."""
        from app.domains.solver.services.expression_parser import ParseError

        with pytest.raises(ParseError, match="max.*not supported"):
            self.parser.parse_expression("max(x, y)", ["x", "y"])

    def test_sum_function(self):
        """sum(x, y, z) should be equivalent to x + y + z."""
        expr = self.parser.parse_expression("sum(x, y, z)", ["x", "y", "z"])
        # Should produce 3 linear terms with coefficient 1
        assert len(expr.terms) == 3
        for term in expr.terms:
            assert abs(term.coefficient - 1.0) < 1e-9

    def test_pow_function(self):
        """pow(x, 2) should be recognized as x^2."""
        expr = self.parser.parse_expression("pow(x, 2)", ["x"])
        quad_terms = [t for t in expr.terms if len(t.variables) == 2]
        assert len(quad_terms) >= 1
        assert quad_terms[0].variables == ["x", "x"]


class TestErrorMessages:
    """Tests for error message quality with position indicators."""

    def setup_method(self):
        self.parser = ExpressionParser()

    def test_error_includes_position(self):
        """Malformed expression error includes character position."""
        with pytest.raises(ValueError) as exc_info:
            self.parser.parse_expression("x + @ y", ["x", "y"])
        error_msg = str(exc_info.value)
        assert "position" in error_msg.lower() or "pos" in error_msg.lower()

    def test_error_includes_arrow(self):
        """Error message includes pointer arrow like Python syntax errors."""
        with pytest.raises(ValueError) as exc_info:
            self.parser.parse_expression("x + @ y", ["x", "y"])
        error_msg = str(exc_info.value)
        assert "^" in error_msg

    def test_error_code_parse_error(self):
        """Error includes EXPR_PARSE_ERROR code."""
        with pytest.raises(ValueError) as exc_info:
            self.parser.parse_expression("x + @ y", ["x", "y"])
        error_msg = str(exc_info.value)
        assert "EXPR_PARSE_ERROR" in error_msg

    def test_empty_parens_error(self):
        """Empty parentheses () should produce a clear error."""
        with pytest.raises(ValueError):
            self.parser.parse_expression("()", ["x"])

    def test_division_by_variable_error(self):
        """Division by a variable should raise a clear error (non-linear)."""
        with pytest.raises(ValueError, match=r"[Dd]ivision|[Nn]on-linear|[Nn]ot supported"):
            self.parser.parse_expression("x / y", ["x", "y"])


class TestDivision:
    """Tests for division handling."""

    def setup_method(self):
        self.parser = ExpressionParser()

    def test_division_by_constant(self):
        """x / 2 should be equivalent to 0.5 * x."""
        expr = self.parser.parse_expression("x / 2", ["x"])
        x_terms = [t for t in expr.terms if "x" in t.variables]
        x_coef = sum(t.coefficient for t in x_terms)
        assert abs(x_coef - 0.5) < 1e-9

    def test_expression_with_division(self):
        """(x + y) / 4 should produce coef=0.25 for both."""
        expr = self.parser.parse_expression("(x + y) / 4", ["x", "y"])
        x_coef = sum(t.coefficient for t in expr.terms if "x" in t.variables)
        y_coef = sum(t.coefficient for t in expr.terms if "y" in t.variables)
        assert abs(x_coef - 0.25) < 1e-9
        assert abs(y_coef - 0.25) < 1e-9
