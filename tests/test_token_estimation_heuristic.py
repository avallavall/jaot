"""Tests for improved token estimation heuristic (Task 5.8).

Verifies that _extract_quantity_numbers correctly filters percentages,
years, and trivially small numbers so that estimate_output_tokens
produces sensible estimates for real user messages.
"""

from app.services.llm.token_estimation import (
    _extract_quantity_numbers,
    estimate_output_tokens,
)
from app.services.platform_settings_service import (
    PlatformSettingsService as PSS,
)


class TestExtractQuantityNumbers:
    """Unit tests for the _extract_quantity_numbers helper."""

    def test_simple_quantity(self):
        assert _extract_quantity_numbers("schedule 50 employees") == [50]

    def test_multiple_quantities(self):
        result = _extract_quantity_numbers("50 employees across 3 shifts")
        assert 50 in result
        assert 3 in result

    def test_filters_percentage_no_space(self):
        """'5%' should be stripped entirely."""
        result = _extract_quantity_numbers("growth of 5% per year")
        assert 5 not in result

    def test_filters_percentage_with_space(self):
        """'12 %' with space should also be stripped."""
        result = _extract_quantity_numbers("reduce costs by 12 %")
        assert 12 not in result

    def test_filters_decimal_percentage(self):
        """'12.5%' should be stripped."""
        result = _extract_quantity_numbers("increase by 12.5%")
        assert 12 not in result
        assert 5 not in result

    def test_filters_year_2026(self):
        result = _extract_quantity_numbers("plan for 2026")
        assert 2026 not in result

    def test_filters_year_1999(self):
        result = _extract_quantity_numbers("data from 1999")
        assert 1999 not in result

    def test_filters_year_2100(self):
        result = _extract_quantity_numbers("forecast to 2100")
        assert 2100 not in result

    def test_does_not_filter_year_like_quantities(self):
        """Numbers outside 1900-2100 should pass through."""
        result = _extract_quantity_numbers("budget of 5000 dollars")
        assert 5000 in result

    def test_filters_zero_and_one(self):
        result = _extract_quantity_numbers("at least 0 or 1 items")
        assert 0 not in result
        assert 1 not in result

    def test_keeps_two(self):
        result = _extract_quantity_numbers("choose between 2 options")
        assert 2 in result

    def test_empty_string(self):
        assert _extract_quantity_numbers("") == []

    def test_no_numbers(self):
        assert _extract_quantity_numbers("minimize cost") == []

    def test_only_percentages(self):
        """If all numbers are percentages, result should be empty."""
        result = _extract_quantity_numbers("5% growth and 10% discount")
        assert result == []

    def test_only_years(self):
        result = _extract_quantity_numbers("from 2020 to 2025")
        assert result == []

    def test_mixed_quantities_and_noise(self):
        """Real-world message with quantities, years, and percentages."""
        msg = "In 2026, schedule 50 employees with 5% overtime across 3 shifts"
        result = _extract_quantity_numbers(msg)
        assert 2026 not in result
        assert 5 not in result  # filtered as percentage
        assert 50 in result
        assert 3 in result

    def test_large_number_preserved(self):
        result = _extract_quantity_numbers("optimize portfolio with 200 stocks")
        assert 200 in result

    def test_percentage_does_not_eat_adjacent_number(self):
        """'5% of 200 items' -- 5 is removed as pct, 200 stays."""
        result = _extract_quantity_numbers("5% of 200 items")
        assert 200 in result
        assert 5 not in result


class TestEstimateOutputTokensWithFiltering:
    """Integration tests verifying estimate_output_tokens uses the improved heuristic."""

    def test_percentage_only_returns_floor(self, db_session):
        """Message with only percentages should return baseline."""
        floor = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        result = estimate_output_tokens("expect 5% growth and 10% discount", db=db_session)
        assert result == floor

    def test_year_only_returns_floor(self, db_session):
        """Message with only years should return baseline."""
        floor = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        result = estimate_output_tokens("plan for 2026", db=db_session)
        assert result == floor

    def test_real_quantity_still_scales(self, db_session):
        """Messages with sufficiently large real quantities scale strictly above floor."""
        floor = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        # n=150 → 500 + 150*40 + 450*30 = 20000 > 16384 floor
        result = estimate_output_tokens(
            "schedule 150 employees across 5 shifts",
            db=db_session,
        )
        assert result > floor

    def test_large_quantity_scales_above_floor(self, db_session):
        floor = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        result = estimate_output_tokens(
            "optimize portfolio with 200 stocks",
            db=db_session,
        )
        assert result > floor

    def test_mixed_noise_and_quantity(self, db_session):
        """Year + percentage + real quantity: only quantity matters and scales strictly above floor."""
        floor = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        # Year 2026 and 15% are filtered noise; the real 250 workers drives scaling
        # n=250 → 500 + 250*40 + 750*30 = 33000 > 16384 floor (capped at 500)
        msg = "In 2026, allocate 250 workers with 15% overtime"
        result = estimate_output_tokens(msg, db=db_session)
        assert result > floor

    def test_no_numbers_returns_floor(self, db_session):
        floor = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        result = estimate_output_tokens("minimize cost", db=db_session)
        assert result == floor

    def test_backward_compat_simple_knapsack(self, db_session):
        """Small numbers that are genuine quantities hit floor."""
        floor = PSS.get_int(db_session, "LLM_MAX_TOKENS")
        result = estimate_output_tokens("simple knapsack with 5 items", db=db_session)
        assert result == floor
