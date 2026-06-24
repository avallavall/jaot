"""Tests for custom exceptions module.

Tests the custom exception classes used throughout the application.
"""

import pytest

from app.shared.core.exceptions import (
    JaotError,
    PluginNotFoundError,
    PluginValidationError,
    SolverError,
)


class TestJaotError:
    """Tests for base JaotError exception."""

    def test_basic_error(self):
        """Test creating a basic error with message."""
        error = JaotError("Something went wrong")

        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.details == {}

    def test_error_with_details(self):
        """Test creating error with details dict."""
        details = {"key": "value", "count": 42}
        error = JaotError("Error with details", details=details)

        assert error.message == "Error with details"
        assert error.details == details
        assert error.details["key"] == "value"

    def test_error_is_exception(self):
        """Test that JaotError can be raised and caught."""
        with pytest.raises(JaotError) as exc_info:
            raise JaotError("Test error")

        assert "Test error" in str(exc_info.value)


class TestPluginNotFoundError:
    """Tests for PluginNotFoundError exception."""

    def test_plugin_not_found(self):
        """Test creating plugin not found error."""
        error = PluginNotFoundError("my-plugin")

        assert "my-plugin" in error.message
        assert error.details["plugin_name"] == "my-plugin"

    def test_inherits_from_jaot_error(self):
        """Test that PluginNotFoundError inherits from JaotError."""
        error = PluginNotFoundError("test")

        assert isinstance(error, JaotError)
        assert isinstance(error, Exception)


class TestPluginValidationError:
    """Tests for PluginValidationError exception."""

    def test_validation_error_with_errors(self):
        """Test creating validation error with error list."""
        errors = ["Field 'name' is required", "Invalid format"]
        error = PluginValidationError(errors)

        assert "validation failed" in error.message.lower()
        assert error.details["errors"] == errors
        assert len(error.details["errors"]) == 2

    def test_validation_error_empty_list(self):
        """Test creating validation error with empty list."""
        error = PluginValidationError([])

        assert error.details["errors"] == []


class TestSolverError:
    """Tests for SolverError exception."""

    def test_solver_error_basic(self):
        """Test creating basic solver error."""
        error = SolverError("Solver failed to converge")

        assert error.message == "Solver failed to converge"
        assert error.details == {}

    def test_solver_error_with_status(self):
        """Test creating solver error with status."""
        error = SolverError("Infeasible problem", solver_status="INFEASIBLE")

        assert error.message == "Infeasible problem"
        assert error.details["solver_status"] == "INFEASIBLE"

    def test_solver_error_inherits_from_jaot_error(self):
        """Test that SolverError inherits from JaotError."""
        error = SolverError("Test")

        assert isinstance(error, JaotError)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
