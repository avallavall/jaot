"""
Exhaustive tests for the public credit calculator endpoint.

Tests cover:
- Basic calculation correctness
- Edge cases: zero variables, max values, boundary conditions
- Formula verification: each component independently
- Cost-by-plan accuracy
- Input validation: negative values, overflow, missing fields
- Minimum credit floor (always >= 1)
"""


class TestCreditCalculatorBasic:
    def test_minimal_problem(self, client):
        """Simplest possible problem: 1 variable, 0 constraints -> exactly 1 credit."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        # base(1) + var(0.1) + mip(0) + con(0) + time(0) = 1.1 -> round(1.1) = 1
        assert data["credits_required"] == 1
        assert data["breakdown"]["base_cost"] == 1
        assert "cost_eur" in data
        assert "cost_by_plan" in data

    def test_zero_variables(self, client):
        """Zero variables should still return exactly 1 credit (floor)."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 0,
            },
        )
        assert response.status_code == 200
        assert response.json()["credits_required"] == 1

    def test_large_problem(self, client):
        """Large problem should cost hundreds of credits, well under the per-solve cap.

        For 10k vars, 7k MIP vars, 8k constraints, 600s time:
        base(1) + var(~159.25) + mip(~167.33) + con(~47.08) + time(9) ~= 383.66
        -> round(383.66) = 384 (strictly inside (100, 500) cap).
        """
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 10000,
                "num_integer_vars": 5000,
                "num_binary_vars": 2000,
                "num_constraints": 8000,
                "time_limit_seconds": 600,
            },
        )
        assert response.status_code == 200
        data = response.json()
        credits = data["credits_required"]
        assert 300 < credits < 500, f"Expected credits in (300, 500), got {credits}"
        # Stays below the max_credits_per_solve cap of 500.
        assert data["breakdown"]["cap_applied"] is False


class TestCreditCalculatorFormula:
    def test_base_cost_is_one(self, client):
        """Base cost should be 1."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 0,
            },
        )
        data = response.json()
        assert data["breakdown"]["base_cost"] == 1

    def test_variable_cost(self, client):
        """10 variables * 0.1 = 1.0 variable cost (linear for <= 100 vars)."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 10,
            },
        )
        data = response.json()
        assert data["breakdown"]["variable_cost"] == 1.0

    def test_mip_penalty(self, client):
        """MIP penalty uses sqrt scaling: sqrt(10) * 2.0 = 6.32 rounded to 2dp."""
        import math

        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 10,
                "num_integer_vars": 10,
            },
        )
        data = response.json()
        expected = round(math.sqrt(10) * 2.0, 2)
        assert data["breakdown"]["mip_penalty"] == expected

    def test_mip_penalty_binary(self, client):
        """Binary vars contribute to mip_penalty via sqrt: sqrt(10) * 2.0."""
        import math

        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 10,
                "num_binary_vars": 10,
            },
        )
        data = response.json()
        expected = round(math.sqrt(10) * 2.0, 2)
        assert data["breakdown"]["mip_penalty"] == expected

    def test_constraint_cost(self, client):
        """20 constraints * 0.05 = 1.0 (linear for <= 50 constraints)."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 1,
                "num_constraints": 20,
            },
        )
        data = response.json()
        assert data["breakdown"]["constraint_cost"] == 1.0

    def test_time_bonus_under_60s(self, client):
        """Time limit <= 60s should have 0 time bonus."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 1,
                "time_limit_seconds": 30,
            },
        )
        data = response.json()
        assert data["breakdown"]["time_bonus"] == 0

    def test_time_bonus_over_60s(self, client):
        """Time limit > 60s should have positive time bonus (1 credit per extra minute)."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 1,
                "time_limit_seconds": 120,
            },
        )
        data = response.json()
        assert data["breakdown"]["time_bonus"] > 0
        # ceil((120 - 60) / 60) = 1
        assert data["breakdown"]["time_bonus"] == 1


class TestCreditCalculatorCostByPlan:
    def test_free_plan_is_zero(self, client):
        """Free plan cost should always be 0."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 100,
            },
        )
        data = response.json()
        assert data["cost_by_plan"]["free"] == 0

    def test_pro_cheaper_than_starter(self, client):
        """Pro should be cheaper per credit than Starter."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 100,
            },
        )
        data = response.json()
        assert data["cost_by_plan"]["pro"] < data["cost_by_plan"]["starter"]

    def test_topup_more_expensive_than_plan(self, client):
        """Top-up 500 should be more expensive per credit than Pro."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 100,
            },
        )
        data = response.json()
        assert data["cost_by_plan"]["topup_500"] > data["cost_by_plan"]["pro"]


class TestCreditCalculatorValidation:
    def test_negative_variables_rejected(self, client):
        """Negative variable count should be rejected."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": -1,
            },
        )
        assert response.status_code == 422

    def test_variables_over_max_rejected(self, client):
        """Variables over 10_000_000 should be rejected."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 10_000_001,
            },
        )
        assert response.status_code == 422

    def test_time_limit_under_1_rejected(self, client):
        """Time limit under 1 second should be rejected."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 10,
                "time_limit_seconds": 0.5,
            },
        )
        assert response.status_code == 422

    def test_time_limit_over_3600_rejected(self, client):
        """Time limit over 3600 seconds should be rejected."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 10,
                "time_limit_seconds": 3601,
            },
        )
        assert response.status_code == 422

    def test_missing_required_field(self, client):
        """Missing num_variables should be rejected."""
        response = client.post("/api/v2/credits/calculator", json={})
        assert response.status_code == 422

    def test_no_auth_required(self, client):
        """Credit calculator should work without authentication."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 10,
            },
        )
        assert response.status_code == 200


class TestCreditCalculatorEdgeCases:
    def test_all_zeros(self, client):
        """All zero inputs should return minimum 1 credit."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 0,
                "num_integer_vars": 0,
                "num_binary_vars": 0,
                "num_constraints": 0,
                "time_limit_seconds": 1,
            },
        )
        assert response.status_code == 200
        assert response.json()["credits_required"] == 1

    def test_max_everything(self, client):
        """Maximum values should hit the per-solve cap at exactly 500.

        Raw formula result ~1599 is well over the 500 cap, so total should
        be clamped exactly to the cap value.
        """
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 100000,
                "num_integer_vars": 100000,
                "num_binary_vars": 100000,
                "num_constraints": 100000,
                "time_limit_seconds": 3600,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["credits_required"] == 500
        assert data["breakdown"]["cap_applied"] is True
        assert data["breakdown"]["max_credits_per_solve"] == 500

    def test_exactly_60s_no_bonus(self, client):
        """Exactly 60s time limit should have 0 bonus."""
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 1,
                "time_limit_seconds": 60,
            },
        )
        assert response.json()["breakdown"]["time_bonus"] == 0

    def test_cost_eur_is_exact(self, client):
        """Cost in EUR for 100 vars is exactly credits * 0.016 = 11 * 0.016 = 0.176.

        Formula: base(1) + var(100*0.1=10) + mip(0) + con(0) + time(0) = 11
        cost_eur = round(11 * 0.016, 4) = 0.176
        """
        response = client.post(
            "/api/v2/credits/calculator",
            json={
                "num_variables": 100,
            },
        )
        data = response.json()
        assert data["credits_required"] == 11
        assert data["cost_eur"] == 0.176
