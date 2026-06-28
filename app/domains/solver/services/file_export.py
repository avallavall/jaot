"""File export service for optimization executions.

Exports solved optimization problems and their solutions in standard formats.

Supported formats:
  - .mps   — MPS (Mathematical Programming System)
  - .lp    — LP (CPLEX LP format)
  - .cip   — CIP (SCIP native format)
  - .sol   — SOL (solution values, SCIP format)
  - .csv   — CSV (variable name, type, value)
  - .json  — JSON (platform OptimizationProblem schema)
"""

import csv
import io
import json
import logging
import os
import tempfile

from app.domains.solver.adapters._scip_model_builder import build_scip_model
from app.schemas.optimization import OptimizationProblem


def extract_solution(result_data: dict) -> dict:
    """Extract solution dict from result_data (handles both 'model' and 'solution' keys)."""
    return result_data.get("model") or result_data.get("solution") or {}


logger = logging.getLogger(__name__)

# Formats that require a SCIP model rebuild + writeProblem
SOLVER_FORMATS = frozenset({"mps", "lp", "cip"})

# Formats generated directly from stored data
TEXT_FORMATS = frozenset({"sol", "csv", "json"})

ALL_EXPORT_FORMATS = SOLVER_FORMATS | TEXT_FORMATS

# Formats valid for exporting a MODEL with no solution yet (sol/csv need a
# solution, so they are excluded). JSON here is the FLAT OptimizationProblem.
MODEL_EXPORT_FORMATS = SOLVER_FORMATS | frozenset({"json"})

# MIME types per format
MIME_TYPES: dict[str, str] = {
    "mps": "application/x-mps",
    "lp": "application/x-lp",
    "cip": "application/x-cip",
    "sol": "text/plain",
    "csv": "text/csv",
    "json": "application/json",
}


class FileExportError(Exception):
    """Raised when file export fails."""


class FileExportService:
    """Export optimization problems and solutions to standard file formats.

    Usage::

        service = FileExportService()
        path = service.export_to_file(problem, result_data, "mps")
        # Caller is responsible for cleaning up the temp file.
    """

    def export_to_file(
        self,
        problem: OptimizationProblem,
        fmt: str,
    ) -> str:
        """Export a problem to MPS/LP/CIP file on disk.

        Args:
            problem: The optimization problem to export.
            fmt: One of "mps", "lp", "cip".

        Returns:
            Path to the temporary file. Caller must delete after use.

        Raises:
            FileExportError: If the export fails.
        """
        if fmt not in SOLVER_FORMATS:
            raise FileExportError(
                f"export_to_file only supports: {', '.join(sorted(SOLVER_FORMATS))}"
            )

        model, _, _ = build_scip_model(problem)

        fd, tmp_path = tempfile.mkstemp(suffix=f".{fmt}")
        os.close(fd)

        try:
            model.writeProblem(tmp_path)
            logger.info(
                "Exported problem to %s (%d vars, %d conss)",
                fmt,
                len(problem.variables),
                len(problem.constraints),
            )
            return tmp_path
        except Exception as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise FileExportError(f"SCIP writeProblem failed: {exc}") from exc

    def export_solution_sol(
        self,
        problem: OptimizationProblem,
        result_data: dict,
    ) -> str:
        """Generate a .sol file content string from solve results.

        SOL format (SCIP-compatible):
            objective value = <value>
            <var_name>  <value>  (obj:<coefficient>)

        Args:
            problem: The optimization problem (for variable metadata).
            result_data: The stored result_data from ModelExecution.

        Returns:
            SOL file content as string.
        """
        solution = extract_solution(result_data)
        objective_value = result_data.get("objective_value")

        if not solution:
            raise FileExportError("No solution data available for SOL export")

        lines: list[str] = []
        if objective_value is not None:
            lines.append(f"objective value = {objective_value}")
        lines.append("")

        for var in problem.variables:
            value = solution.get(var.name, 0.0)
            lines.append(f"{var.name}\t\t{value}")

        lines.append("")
        return "\n".join(lines)

    def export_solution_csv(
        self,
        problem: OptimizationProblem,
        result_data: dict,
    ) -> str:
        """Generate a CSV string from solve results.

        Columns: variable_name, type, lower_bound, upper_bound, value

        Args:
            problem: The optimization problem (for variable metadata).
            result_data: The stored result_data from ModelExecution.

        Returns:
            CSV content as string.
        """
        solution = extract_solution(result_data)

        if not solution:
            raise FileExportError("No solution data available for CSV export")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["variable_name", "type", "lower_bound", "upper_bound", "value"])

        for var in problem.variables:
            value = solution.get(var.name, "")
            writer.writerow(
                [
                    var.name,
                    var.type.value,
                    var.lower_bound if var.lower_bound is not None else "",
                    var.upper_bound if var.upper_bound is not None else "",
                    value,
                ]
            )

        return output.getvalue()

    def export_json(
        self,
        problem: OptimizationProblem,
        result_data: dict | None,
    ) -> str:
        """Export the problem (and optionally results) as JSON.

        Returns:
            JSON string.
        """
        data: dict = {"problem": problem.model_dump(mode="json")}
        if result_data:
            data["result"] = result_data
        return json.dumps(data, indent=2, ensure_ascii=False)

    def export_model_json(self, problem: OptimizationProblem) -> str:
        """Export just the model as a FLAT OptimizationProblem JSON.

        Unlike :meth:`export_json` (which nests the problem under ``"problem"``
        alongside results), this emits a bare OptimizationProblem so it
        round-trips straight back through the importer.
        """
        return json.dumps(problem.model_dump(mode="json"), indent=2, ensure_ascii=False)


# Singleton
_file_export_service: FileExportService | None = None


def get_file_export_service() -> FileExportService:
    """Get or create FileExportService singleton."""
    global _file_export_service
    if _file_export_service is None:
        _file_export_service = FileExportService()
    return _file_export_service
