"""Tests for file import service and API endpoints.

Unit tests for FileImportService + CIP parser, and integration tests
for the /api/v2/solve/import endpoints against real PostgreSQL.

Fixtures:
  - simple.mps / simple.lp / simple.json — 3-var continuous LP
  - mip_knapsack.mps — 5 binary variable knapsack
  - production_mix.lp — 3 integer + 2 continuous, mixed constraints
  - infeasible.lp — contradictory constraints
  - unbounded.lp — maximize with no upper bound
  - large_transport.json — 80 variables, 24 constraints
"""

import gzip
import json
import os
import tempfile

import pytest

from app.domains.solver.services.cip_parser import parse_cip_constraints
from app.domains.solver.services.file_import import (
    FileImportError,
    FileImportService,
    validate_extension,
)
from app.schemas.optimization import ObjectiveSense, VariableType

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(filename: str) -> bytes:
    """Read a fixture file as bytes."""
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, "rb") as f:
        return f.read()


def _var_names(problem) -> list[str]:
    """Extract sorted variable names from problem."""
    return sorted(v.name for v in problem.variables)


def _var_by_name(problem, name: str):
    """Find a variable by name in a problem."""
    for v in problem.variables:
        if v.name == name:
            return v
    raise ValueError(f"Variable '{name}' not found")


def _constraint_by_name(problem, name: str):
    """Find a constraint by name in a problem."""
    for c in problem.constraints:
        if c.name == name:
            return c
    raise ValueError(f"Constraint '{name}' not found")


# UNIT TESTS — FileImportService: simple.mps


class TestImportSimpleMps:
    """Exact assertions for simple.mps: 3-variable continuous LP."""

    def setup_method(self):
        self.service = FileImportService()
        self.problem = self.service.import_from_file(_read_fixture("simple.mps"), "simple.mps")

    def test_variable_count(self):
        assert len(self.problem.variables) == 3

    def test_variable_names(self):
        assert _var_names(self.problem) == ["x1", "x2", "x3"]

    def test_all_continuous(self):
        for var in self.problem.variables:
            assert var.type == VariableType.CONTINUOUS

    def test_bounds_are_0_to_5(self):
        for var in self.problem.variables:
            assert var.lower_bound == 0.0
            assert var.upper_bound == 5.0

    def test_objective_sense_minimize(self):
        assert self.problem.objective.sense == ObjectiveSense.MINIMIZE

    def test_objective_expression_coefficients(self):
        expr = self.problem.objective.expression
        assert "x1" in expr
        assert "2.0*x2" in expr
        assert "3.0*x3" in expr

    def test_constraint_count(self):
        assert len(self.problem.constraints) == 2

    def test_constraint_names(self):
        names = sorted(c.name for c in self.problem.constraints)
        assert names == ["c1", "c2"]

    def test_c1_expression(self):
        c1 = _constraint_by_name(self.problem, "c1")
        assert "2.0*x1" in c1.expression
        assert "<= 10.0" in c1.expression

    def test_c2_expression(self):
        c2 = _constraint_by_name(self.problem, "c2")
        assert "3.0*x2" in c2.expression
        assert "<= 8.0" in c2.expression

    def test_problem_name(self):
        assert self.problem.name == "simple"

    def test_objective_sense_override(self):
        problem = self.service.import_from_file(
            _read_fixture("simple.mps"), "simple.mps", ObjectiveSense.MAXIMIZE
        )
        assert problem.objective.sense == ObjectiveSense.MAXIMIZE

    def test_gzipped_import(self):
        gz_bytes = gzip.compress(_read_fixture("simple.mps"))
        problem = self.service.import_from_file(gz_bytes, "simple.mps.gz")
        assert len(problem.variables) == 3
        assert _var_names(problem) == ["x1", "x2", "x3"]


# UNIT TESTS — FileImportService: simple.lp


class TestImportSimpleLp:
    """Exact assertions for simple.lp: 3-variable continuous LP."""

    def setup_method(self):
        self.service = FileImportService()
        self.problem = self.service.import_from_file(_read_fixture("simple.lp"), "simple.lp")

    def test_variable_count(self):
        assert len(self.problem.variables) == 3

    def test_variable_names(self):
        assert _var_names(self.problem) == ["x1", "x2", "x3"]

    def test_all_continuous(self):
        for var in self.problem.variables:
            assert var.type == VariableType.CONTINUOUS

    def test_bounds_are_0_to_5(self):
        for var in self.problem.variables:
            assert var.lower_bound == 0.0
            assert var.upper_bound == 5.0

    def test_objective_sense_minimize(self):
        assert self.problem.objective.sense == ObjectiveSense.MINIMIZE

    def test_objective_expression_coefficients(self):
        expr = self.problem.objective.expression
        assert "x1" in expr
        assert "2.0*x2" in expr
        assert "3.0*x3" in expr

    def test_constraint_count(self):
        assert len(self.problem.constraints) == 2

    def test_constraint_names(self):
        names = sorted(c.name for c in self.problem.constraints)
        assert names == ["c1", "c2"]

    def test_c1_expression(self):
        c1 = _constraint_by_name(self.problem, "c1")
        assert "2.0*x1" in c1.expression
        assert "<= 10.0" in c1.expression

    def test_c2_expression(self):
        c2 = _constraint_by_name(self.problem, "c2")
        assert "3.0*x2" in c2.expression
        assert "<= 8.0" in c2.expression

    def test_gzipped_import(self):
        gz_bytes = gzip.compress(_read_fixture("simple.lp"))
        problem = self.service.import_from_file(gz_bytes, "simple.lp.gz")
        assert len(problem.variables) == 3
        assert _var_names(problem) == ["x1", "x2", "x3"]


# UNIT TESTS — FileImportService: simple.json


class TestImportSimpleJson:
    """Exact assertions for simple.json: direct JSON schema import."""

    def setup_method(self):
        self.service = FileImportService()
        self.problem = self.service.import_from_file(_read_fixture("simple.json"), "simple.json")

    def test_problem_name(self):
        assert self.problem.name == "simple_test"

    def test_variable_count(self):
        assert len(self.problem.variables) == 3

    def test_variable_names(self):
        assert _var_names(self.problem) == ["x1", "x2", "x3"]

    def test_all_continuous(self):
        for var in self.problem.variables:
            assert var.type == VariableType.CONTINUOUS

    def test_bounds(self):
        for var in self.problem.variables:
            assert var.lower_bound == 0
            assert var.upper_bound == 5

    def test_objective_sense(self):
        assert self.problem.objective.sense == ObjectiveSense.MINIMIZE

    def test_objective_expression(self):
        assert self.problem.objective.expression == "x1 + 2*x2 + 3*x3"

    def test_constraint_count(self):
        assert len(self.problem.constraints) == 2

    def test_constraint_names(self):
        names = sorted(c.name for c in self.problem.constraints)
        assert names == ["c1", "c2"]


# UNIT TESTS — FileImportService: wrapped execution-export JSON


class TestImportWrappedExecutionJson:
    """Regression for the execution-export JSON shape {"problem", "result"}.

    Execution / "export result" downloads wrap the model under a "problem"
    key (alongside "result"). The importer must unwrap it so the
    export->import round-trip works instead of failing with a schema
    mismatch ("No variables found"). A flat OptimizationProblem always
    carries "variables" at the top level, so the unwrap is unambiguous.
    """

    def setup_method(self):
        self.service = FileImportService()
        self._flat = {
            "name": "wrapped_test",
            "objective": {"sense": "minimize", "expression": "x1 + 2*x2"},
            "variables": [
                {"name": "x1", "type": "continuous", "lower_bound": 0, "upper_bound": 5},
                {"name": "x2", "type": "continuous", "lower_bound": 0, "upper_bound": 5},
            ],
            "constraints": [
                {"name": "c1", "expression": "x1 + x2 <= 4"},
            ],
        }

    def test_unwraps_wrapped_problem(self):
        # CONTRACT-TEST: execution-export JSON ({problem,result}) round-trips back through import
        wrapped = json.dumps(
            {"problem": self._flat, "result": {"status": "optimal", "objective_value": 0.0}}
        ).encode()
        problem = self.service.import_from_file(wrapped, "exe_export.json")
        assert problem.name == "wrapped_test"
        assert _var_names(problem) == ["x1", "x2"]
        assert len(problem.constraints) == 1

    def test_wrapped_without_result_imports(self):
        wrapped = json.dumps({"problem": self._flat}).encode()
        problem = self.service.import_from_file(wrapped, "model.json")
        assert _var_names(problem) == ["x1", "x2"]

    def test_flat_problem_still_imports(self):
        """A flat OptimizationProblem (no "problem" wrapper) is untouched."""
        flat = json.dumps(self._flat).encode()
        problem = self.service.import_from_file(flat, "model.json")
        assert problem.name == "wrapped_test"
        assert len(problem.variables) == 2


# UNIT TESTS — FileImportService: mip_knapsack.mps


class TestImportMipKnapsack:
    """Exact assertions for mip_knapsack.mps: 5 binary var knapsack."""

    def setup_method(self):
        self.service = FileImportService()
        self.problem = self.service.import_from_file(
            _read_fixture("mip_knapsack.mps"), "mip_knapsack.mps"
        )

    def test_variable_count(self):
        assert len(self.problem.variables) == 5

    def test_variable_names(self):
        assert _var_names(self.problem) == ["x1", "x2", "x3", "x4", "x5"]

    def test_all_binary(self):
        for var in self.problem.variables:
            assert var.type == VariableType.BINARY, (
                f"Variable {var.name} should be BINARY, got {var.type}"
            )

    def test_binary_bounds(self):
        for var in self.problem.variables:
            assert var.lower_bound == 0.0
            assert var.upper_bound == 1.0

    def test_objective_sense(self):
        # MPS uses negative coefficients with MINIMIZE to emulate MAXIMIZE
        assert self.problem.objective.sense == ObjectiveSense.MINIMIZE

    def test_objective_has_all_variables(self):
        expr = self.problem.objective.expression
        for name in ["x1", "x2", "x3", "x4", "x5"]:
            assert name in expr

    def test_single_capacity_constraint(self):
        assert len(self.problem.constraints) == 1

    def test_constraint_is_le(self):
        c = self.problem.constraints[0]
        assert "<=" in c.expression

    def test_constraint_name(self):
        assert self.problem.constraints[0].name == "capacity"

    def test_constraint_rhs(self):
        assert "7.0" in self.problem.constraints[0].expression

    def test_problem_name(self):
        assert self.problem.name == "knapsack"


# UNIT TESTS — FileImportService: production_mix.lp


class TestImportProductionMix:
    """Exact assertions for production_mix.lp: mixed types and constraints."""

    def setup_method(self):
        self.service = FileImportService()
        self.problem = self.service.import_from_file(
            _read_fixture("production_mix.lp"), "production_mix.lp"
        )

    def test_variable_count(self):
        assert len(self.problem.variables) == 5

    def test_variable_names(self):
        assert _var_names(self.problem) == ["p1", "p2", "p3", "r1", "r2"]

    def test_integer_variables(self):
        integer_vars = [v for v in self.problem.variables if v.type == VariableType.INTEGER]
        assert len(integer_vars) == 3
        integer_names = sorted(v.name for v in integer_vars)
        assert integer_names == ["p1", "p2", "p3"]

    def test_continuous_variables(self):
        cont_vars = [v for v in self.problem.variables if v.type == VariableType.CONTINUOUS]
        assert len(cont_vars) == 2
        cont_names = sorted(v.name for v in cont_vars)
        assert cont_names == ["r1", "r2"]

    def test_negative_lower_bound_preserved(self):
        r1 = _var_by_name(self.problem, "r1")
        assert r1.lower_bound == -10.0

    def test_specific_bounds(self):
        assert _var_by_name(self.problem, "p1").upper_bound == 40.0
        assert _var_by_name(self.problem, "p2").upper_bound == 30.0
        assert _var_by_name(self.problem, "p3").upper_bound == 50.0
        assert _var_by_name(self.problem, "r1").upper_bound == 60.0
        assert _var_by_name(self.problem, "r2").upper_bound == 80.0

    def test_objective_sense_minimize(self):
        assert self.problem.objective.sense == ObjectiveSense.MINIMIZE

    def test_objective_coefficient_pi(self):
        """Verify coefficient 3.14159 is preserved numerically."""
        expr = self.problem.objective.expression
        assert "3.14159" in expr

    def test_objective_coefficient_e(self):
        """Verify coefficient 2.71828 is preserved numerically."""
        expr = self.problem.objective.expression
        assert "2.71828" in expr

    def test_constraint_count(self):
        assert len(self.problem.constraints) == 3

    def test_has_le_constraint(self):
        capacity = _constraint_by_name(self.problem, "capacity")
        assert "<=" in capacity.expression

    def test_has_ge_constraint(self):
        demand = _constraint_by_name(self.problem, "demand_min")
        assert ">=" in demand.expression

    def test_has_equality_constraint(self):
        balance = _constraint_by_name(self.problem, "balance")
        assert "==" in balance.expression


# UNIT TESTS — FileImportService: infeasible.lp


class TestImportInfeasible:
    """Assertions for infeasible.lp: parsing succeeds, contradictory constraints."""

    def setup_method(self):
        self.service = FileImportService()
        self.problem = self.service.import_from_file(
            _read_fixture("infeasible.lp"), "infeasible.lp"
        )

    def test_parsing_succeeds(self):
        """Infeasible problem should still parse successfully."""
        assert self.problem is not None

    def test_variable_count(self):
        assert len(self.problem.variables) == 2

    def test_variable_names(self):
        assert _var_names(self.problem) == ["x1", "x2"]

    def test_constraint_count(self):
        assert len(self.problem.constraints) == 2

    def test_has_le_constraint(self):
        upper = _constraint_by_name(self.problem, "upper")
        assert "<= 1.0" in upper.expression

    def test_has_ge_constraint(self):
        lower = _constraint_by_name(self.problem, "lower")
        assert ">= 5.0" in lower.expression


# UNIT TESTS — FileImportService: unbounded.lp


class TestImportUnbounded:
    """Assertions for unbounded.lp: parsing succeeds, no upper bound."""

    def setup_method(self):
        self.service = FileImportService()
        self.problem = self.service.import_from_file(_read_fixture("unbounded.lp"), "unbounded.lp")

    def test_parsing_succeeds(self):
        assert self.problem is not None

    def test_variable_count(self):
        assert len(self.problem.variables) == 1

    def test_variable_name(self):
        assert self.problem.variables[0].name == "x"

    def test_no_upper_bound(self):
        assert self.problem.variables[0].upper_bound is None

    def test_lower_bound_zero(self):
        assert self.problem.variables[0].lower_bound == 0.0

    def test_objective_maximize(self):
        assert self.problem.objective.sense == ObjectiveSense.MAXIMIZE


# UNIT TESTS — FileImportService: large_transport.json


class TestImportLargeTransport:
    """Assertions for large_transport.json: 80 vars, 24 constraints."""

    def setup_method(self):
        self.service = FileImportService()
        self.problem = self.service.import_from_file(
            _read_fixture("large_transport.json"), "large_transport.json"
        )

    def test_variable_count_at_least_50(self):
        assert len(self.problem.variables) >= 50

    def test_exact_variable_count(self):
        assert len(self.problem.variables) == 80

    def test_constraint_count_at_least_20(self):
        assert len(self.problem.constraints) >= 20

    def test_exact_constraint_count(self):
        assert len(self.problem.constraints) == 24

    def test_problem_name(self):
        assert self.problem.name == "transport_network"

    def test_objective_sense_minimize(self):
        assert self.problem.objective.sense == ObjectiveSense.MINIMIZE

    def test_round_trip_preserves_all_variables(self):
        """Import from JSON preserves all 80 variable definitions."""
        raw = json.loads(_read_fixture("large_transport.json"))
        raw_names = sorted(v["name"] for v in raw["variables"])
        imported_names = _var_names(self.problem)
        assert raw_names == imported_names

    def test_round_trip_preserves_all_constraints(self):
        """Import from JSON preserves all 24 constraint definitions."""
        raw = json.loads(_read_fixture("large_transport.json"))
        raw_names = sorted(c["name"] for c in raw["constraints"])
        imported_names = sorted(c.name for c in self.problem.constraints)
        assert raw_names == imported_names

    def test_variable_bounds_preserved(self):
        """Spot-check that bounds are preserved."""
        x1_1 = _var_by_name(self.problem, "x1_1")
        assert x1_1.lower_bound == 0
        assert x1_1.upper_bound == 500

    def test_supply_constraint_structure(self):
        """Supply constraints reference correct source variables."""
        supply_1 = _constraint_by_name(self.problem, "supply_1")
        assert "x1_1" in supply_1.expression
        assert "x1_10" in supply_1.expression
        assert "<=" in supply_1.expression

    def test_demand_constraint_structure(self):
        """Demand constraints reference correct destination variables."""
        demand_1 = _constraint_by_name(self.problem, "demand_1")
        assert "x1_1" in demand_1.expression
        assert "x8_1" in demand_1.expression
        assert ">=" in demand_1.expression


class TestCrossFormatConsistency:
    """Import MPS and LP of the same problem and verify consistency."""

    def setup_method(self):
        self.service = FileImportService()
        self.mps_problem = self.service.import_from_file(_read_fixture("simple.mps"), "simple.mps")
        self.lp_problem = self.service.import_from_file(_read_fixture("simple.lp"), "simple.lp")

    def test_same_variable_count(self):
        assert len(self.mps_problem.variables) == len(self.lp_problem.variables)

    def test_same_variable_names(self):
        assert _var_names(self.mps_problem) == _var_names(self.lp_problem)

    def test_same_variable_types(self):
        mps_types = {v.name: v.type for v in self.mps_problem.variables}
        lp_types = {v.name: v.type for v in self.lp_problem.variables}
        assert mps_types == lp_types

    def test_same_variable_bounds(self):
        mps_bounds = {v.name: (v.lower_bound, v.upper_bound) for v in self.mps_problem.variables}
        lp_bounds = {v.name: (v.lower_bound, v.upper_bound) for v in self.lp_problem.variables}
        assert mps_bounds == lp_bounds

    def test_same_constraint_count(self):
        assert len(self.mps_problem.constraints) == len(self.lp_problem.constraints)

    def test_same_objective_sense(self):
        assert self.mps_problem.objective.sense == self.lp_problem.objective.sense

    def test_same_objective_expression(self):
        assert self.mps_problem.objective.expression == self.lp_problem.objective.expression


class TestImportErrors:
    """Error handling: bad schemas, unsupported formats, size limits."""

    def setup_method(self):
        self.service = FileImportService()

    # --- JSON errors ---

    def test_json_invalid_schema(self):
        bad_json = json.dumps({"name": "bad", "variables": []}).encode()
        with pytest.raises(FileImportError, match="schema"):
            self.service.import_from_file(bad_json, "bad.json")

    def test_json_invalid_syntax(self):
        with pytest.raises(FileImportError, match="Invalid JSON"):
            self.service.import_from_file(b"{not valid json", "bad.json")

    def test_json_size_limit(self):
        big_json = b"x" * (10 * 1024 * 1024 + 1)
        with pytest.raises(FileImportError, match="too large"):
            self.service.import_from_file(big_json, "big.json")

    # --- Unsupported formats ---

    def test_reject_xlsx(self):
        with pytest.raises(FileImportError, match="Unsupported"):
            self.service.import_from_file(b"fake", "model.xlsx")

    def test_reject_txt(self):
        with pytest.raises(FileImportError, match="Unsupported"):
            self.service.import_from_file(b"fake", "model.txt")

    def test_reject_csv(self):
        with pytest.raises(FileImportError, match="Unsupported"):
            self.service.import_from_file(b"fake", "data.csv")

    # --- Corrupt files ---

    def test_reject_corrupt_mps(self):
        with pytest.raises(FileImportError, match="SCIP failed"):
            self.service.import_from_file(b"not a valid mps file", "bad.mps")

    def test_reject_corrupt_lp(self):
        with pytest.raises(FileImportError, match="(SCIP failed|No variables found)"):
            self.service.import_from_file(b"garbage content here", "bad.lp")

    def test_reject_corrupt_gzip(self):
        with pytest.raises(FileImportError, match="decompress"):
            self.service.import_from_file(b"not gzip data", "model.mps.gz")

    # --- Size limits ---

    def test_reject_solver_file_over_100mb(self):
        big_bytes = b"x" * (100 * 1024 * 1024 + 1)
        with pytest.raises(FileImportError, match="too large"):
            self.service.import_from_file(big_bytes, "huge.mps")

    # --- Empty / whitespace ---

    def test_empty_filename_unsupported(self):
        """Empty filename has no valid extension."""
        with pytest.raises(FileImportError, match="Unsupported"):
            self.service.import_from_file(b"content", "")

    def test_whitespace_only_mps(self):
        """MPS file with only whitespace should fail SCIP parsing."""
        with pytest.raises(FileImportError, match="SCIP failed"):
            self.service.import_from_file(b"   \n\t\n  ", "whitespace.mps")

    def test_whitespace_only_json(self):
        """JSON file with only whitespace should fail JSON parsing."""
        with pytest.raises(FileImportError, match="Invalid JSON"):
            self.service.import_from_file(b"   \n\t\n  ", "whitespace.json")


# UNIT TESTS — Payload bomb / DoS defenses


class TestImportPayloadBombs:
    """Defense against malicious upload payloads.

    Covers:
      - gzip bomb: tiny compressed file that inflates to gigabytes.
      - deeply nested JSON: Python stack overflow in json.loads.
      - zip-slip-style filename: ``../../../etc/passwd`` in the upload name.
    """

    def setup_method(self):
        self.service = FileImportService()

    def test_import_gzip_bomb_rejected(self):
        """A gzip file that inflates past MAX_IMPORT_SIZE must be rejected."""
        from app.schemas.file_io import MAX_IMPORT_SIZE

        # Build a payload that inflates to just over the 100 MB cap.
        # A buffer of MAX_IMPORT_SIZE + 1 bytes of 'A' compresses to a few KB.
        inflated = b"A" * (MAX_IMPORT_SIZE + 1)
        compressed = gzip.compress(inflated)
        # Sanity: compressed size must be much smaller than the inflated size
        # (otherwise the test isn't exercising the cap path).
        assert len(compressed) < 1 * 1024 * 1024  # < 1 MB compressed

        with pytest.raises(FileImportError, match="gzip bomb|exceeds"):
            self.service.import_from_file(compressed, "bomb.mps.gz")

    def test_import_deeply_nested_json_rejected(self):
        """Deeply nested JSON must be rejected without crashing the worker."""
        depth = 5000  # Well above Python's default recursion limit (1000).
        payload = (b'{"a":' * depth) + b"1" + (b"}" * depth)
        with pytest.raises(FileImportError, match="Invalid JSON"):
            self.service.import_from_file(payload, "deep.json")

    def test_import_zip_slip_filename_rejected(self):
        """A filename containing path traversal must be handled safely.

        The extension validator normalizes on the trailing suffix so the
        traversal segment has no effect. The content is still written to a
        mkstemp-generated path, so no traversal actually occurs on disk.
        The test also verifies that no file appears outside the system temp
        directory.
        """
        import glob

        before = set(glob.glob("/etc/passwd*"))
        try:
            # Syntactically invalid MPS content — we just want to confirm that
            # the filename passes the extension check and does NOT cause any
            # file to be written outside the temp dir.
            self.service.import_from_file(b"garbage", "../../../etc/passwd.mps")
        except FileImportError:
            # Expected: SCIP failed to parse the garbage content.
            pass
        after = set(glob.glob("/etc/passwd*"))
        # No new file must have been created by the import call.
        assert before == after


class TestExtensionValidation:
    """validate_extension returns normalized extension."""

    def test_mps(self):
        assert validate_extension("model.mps") == ".mps"

    def test_lp(self):
        assert validate_extension("model.lp") == ".lp"

    def test_cip(self):
        assert validate_extension("model.cip") == ".cip"

    def test_json(self):
        assert validate_extension("model.json") == ".json"

    def test_mps_gz(self):
        assert validate_extension("model.mps.gz") == ".mps.gz"

    def test_lp_gz(self):
        assert validate_extension("model.lp.gz") == ".lp.gz"

    def test_case_insensitive(self):
        assert validate_extension("MODEL.MPS") == ".mps"

    def test_case_insensitive_gz(self):
        assert validate_extension("MODEL.MPS.GZ") == ".mps.gz"


class TestCipParser:
    """Unit tests for CIP constraint parser."""

    def test_parse_known_cip_output(self):
        """Parse a known CIP output and verify constraint expressions."""
        cip_content = (
            "STATISTICS\n"
            "  Problem name: test\n"
            "VARIABLES\n"
            "CONSTRAINTS\n"
            "  [linear] c1: +2<x1> +1<x2> +1<x3> <= 10;\n"
            "  [linear] c2: +1<x1> +3<x2> +1<x3> <= 8;\n"
            "OBJECTIVE\n"
        )

        fd, path = tempfile.mkstemp(suffix=".cip")
        try:
            os.write(fd, cip_content.encode())
            os.close(fd)

            constraints = parse_cip_constraints(path)
            assert len(constraints) == 2

            assert constraints[0].name == "c1"
            assert "<=" in constraints[0].expression
            assert "x1" in constraints[0].expression
            assert "10" in constraints[0].expression

            assert constraints[1].name == "c2"
            assert "8" in constraints[1].expression
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_parse_empty_cip(self):
        """Parsing a CIP file with no [linear] sections returns empty list."""
        fd, path = tempfile.mkstemp(suffix=".cip")
        try:
            os.write(fd, b"STATISTICS\nVARIABLES\nOBJECTIVE\n")
            os.close(fd)

            constraints = parse_cip_constraints(path)
            assert constraints == []
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_parse_cip_sanitizes_names(self):
        """Variable names with special characters are sanitized."""
        cip_content = "[linear] my-cons.1: +1<x[0]> +2<y.val> <= 5;\n"

        fd, path = tempfile.mkstemp(suffix=".cip")
        try:
            os.write(fd, cip_content.encode())
            os.close(fd)

            constraints = parse_cip_constraints(path)
            assert len(constraints) == 1
            expr = constraints[0].expression
            assert "x_0_" in expr
            assert "y_val" in expr
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


# INTEGRATION TESTS — API Endpoints: Preview


class TestImportPreviewEndpoint:
    """Integration tests for POST /api/v2/solve/import/preview."""

    def test_preview_mps_exact_metadata(self, authenticated_client):
        """Upload simple.mps: verify exact variable/constraint counts."""
        file_bytes = _read_fixture("simple.mps")
        resp = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("simple.mps", file_bytes, "application/octet-stream")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["source_format"] == "mps"
        assert data["metadata"]["num_variables"] == 3
        assert data["metadata"]["num_constraints"] == 2
        assert data["metadata"]["num_continuous"] == 3
        assert data["metadata"]["num_integer"] == 0
        assert data["metadata"]["num_binary"] == 0
        assert data["metadata"]["original_filename"] == "simple.mps"

    def test_preview_json(self, authenticated_client):
        """Upload simple.json: verify round-tripped problem name."""
        file_bytes = _read_fixture("simple.json")
        resp = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("simple.json", file_bytes, "application/octet-stream")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["problem"]["name"] == "simple_test"
        assert data["metadata"]["source_format"] == "json"
        assert data["metadata"]["num_variables"] == 3

    def test_preview_knapsack_binary_counts(self, authenticated_client):
        """Upload mip_knapsack.mps: verify binary variable count in metadata."""
        file_bytes = _read_fixture("mip_knapsack.mps")
        resp = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("mip_knapsack.mps", file_bytes, "application/octet-stream")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["num_variables"] == 5
        assert data["metadata"]["num_binary"] == 5
        assert data["metadata"]["num_integer"] == 0
        assert data["metadata"]["num_continuous"] == 0

    def test_preview_production_mix_counts(self, authenticated_client):
        """Upload production_mix.lp: verify mixed type counts."""
        file_bytes = _read_fixture("production_mix.lp")
        resp = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("production_mix.lp", file_bytes, "application/octet-stream")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["num_variables"] == 5
        assert data["metadata"]["num_integer"] == 3
        assert data["metadata"]["num_continuous"] == 2
        assert data["metadata"]["num_constraints"] == 3

    def test_preview_large_transport(self, authenticated_client):
        """Upload large_transport.json: verify large problem metadata."""
        file_bytes = _read_fixture("large_transport.json")
        resp = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("large_transport.json", file_bytes, "application/octet-stream")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["num_variables"] == 80
        assert data["metadata"]["num_constraints"] == 24

    def test_preview_unsupported_format(self, authenticated_client):
        resp = authenticated_client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("model.xlsx", b"fake", "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_preview_no_auth(self, client):
        file_bytes = _read_fixture("simple.mps")
        resp = client.post(
            "/api/v2/solve/import/preview",
            files={"file": ("simple.mps", file_bytes, "application/octet-stream")},
        )
        assert resp.status_code == 401


# INTEGRATION TESTS — API Endpoints: Import and Solve


class TestImportAndSolveEndpoint:
    """Integration tests for POST /api/v2/solve/import."""

    def test_solve_simple_lp_optimal(self, authenticated_client):
        """Upload simple.lp: expect optimal status."""
        file_bytes = _read_fixture("simple.lp")
        resp = authenticated_client.post(
            "/api/v2/solve/import",
            files={"file": ("simple.lp", file_bytes, "application/octet-stream")},
            data={"time_limit_seconds": "30"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("optimal", "feasible")
        assert data["objective_value"] is not None
        assert data["solution"] is not None
        # Solution should have exactly 3 variables
        assert len(data["solution"]) == 3

    def test_solve_knapsack_optimal(self, authenticated_client):
        """Upload mip_knapsack.mps: expect optimal or feasible status."""
        file_bytes = _read_fixture("mip_knapsack.mps")
        resp = authenticated_client.post(
            "/api/v2/solve/import",
            files={"file": ("mip_knapsack.mps", file_bytes, "application/octet-stream")},
            data={"time_limit_seconds": "30"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("optimal", "feasible")
        assert data["solution"] is not None
        # All binary variable values should be 0 or 1
        for name, val in data["solution"].items():
            assert val in (0.0, 1.0), f"{name} should be binary, got {val}"

    def test_solve_infeasible(self, authenticated_client):
        """Upload infeasible.lp: expect infeasible status."""
        file_bytes = _read_fixture("infeasible.lp")
        resp = authenticated_client.post(
            "/api/v2/solve/import",
            files={"file": ("infeasible.lp", file_bytes, "application/octet-stream")},
            data={"time_limit_seconds": "30"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "infeasible"

    def test_solve_unbounded(self, authenticated_client):
        """Upload unbounded.lp: expect unbounded or error status."""
        file_bytes = _read_fixture("unbounded.lp")
        resp = authenticated_client.post(
            "/api/v2/solve/import",
            files={"file": ("unbounded.lp", file_bytes, "application/octet-stream")},
            data={"time_limit_seconds": "30"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("unbounded", "error")

    def test_solve_no_auth(self, client):
        file_bytes = _read_fixture("simple.lp")
        resp = client.post(
            "/api/v2/solve/import",
            files={"file": ("simple.lp", file_bytes, "application/octet-stream")},
        )
        assert resp.status_code == 401

    def test_solve_insufficient_credits(self, authenticated_client, test_organization, db_session):
        """Import with zero credits returns 402."""
        test_organization.credits_balance = 0
        db_session.commit()

        file_bytes = _read_fixture("simple.lp")
        resp = authenticated_client.post(
            "/api/v2/solve/import",
            files={"file": ("simple.lp", file_bytes, "application/octet-stream")},
        )
        assert resp.status_code == 402
