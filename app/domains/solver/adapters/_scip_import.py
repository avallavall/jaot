"""File import service for optimization models — absorbed into adapters/ per Phase 4 Plan 03 / D-07.

Imports optimization problems from standard file formats (MPS, LP, CIP, JSON)
into the platform's OptimizationProblem schema. Uses SCIP as the file reader
for MPS/LP/CIP formats.

Supported formats:
  - .mps, .mps.gz — MPS (Mathematical Programming System)
  - .lp, .lp.gz   — LP (CPLEX LP format)
  - .cip           — CIP (SCIP native format)
  - .json          — Direct JAOT JSON schema

Original path: app/domains/solver/services/file_import.py
Canonical path: app/domains/solver/adapters/_scip_import.py
"""

import gzip
import io
import json
import logging
import os
import tempfile

from pyscipopt import Model

from app.domains.solver.services._naming import sanitize_var_name
from app.domains.solver.services.cip_parser import parse_cip_constraints
from app.schemas.file_io import (
    ALL_EXTENSIONS,
    GZIP_EXTENSIONS,
    MAX_IMPORT_SIZE,
    MAX_JSON_DEPTH,
    MAX_JSON_SIZE,
    SUPPORTED_FORMAT_EXTENSIONS,
)
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)

logger = logging.getLogger(__name__)

# SCIP variable type mapping
_SCIP_VTYPE_MAP: dict[str, VariableType] = {
    "BINARY": VariableType.BINARY,
    "INTEGER": VariableType.INTEGER,
    "CONTINUOUS": VariableType.CONTINUOUS,
    "IMPLINT": VariableType.INTEGER,
}


_sanitize_var_name = sanitize_var_name  # local alias for brevity


class FileImportError(Exception):
    """Raised when file import fails."""


def validate_extension(filename: str) -> str:
    """Validate and return the normalized file extension.

    Returns the extension (e.g., '.mps', '.mps.gz').

    Raises:
        FileImportError: If the extension is not supported.
    """
    lower = filename.lower()

    for gz_ext in GZIP_EXTENSIONS:
        if lower.endswith(gz_ext):
            return gz_ext

    _, ext = os.path.splitext(lower)
    if ext not in SUPPORTED_FORMAT_EXTENSIONS:
        raise FileImportError(
            f"Unsupported file format: '{ext}'. Supported: {', '.join(sorted(ALL_EXTENSIONS))}"
        )
    return ext


class FileImportService:
    """Import optimization problems from standard file formats.

    Usage::

        service = FileImportService()
        problem = service.import_from_file(file_bytes, "model.mps")
    """

    def import_from_file(
        self,
        file_bytes: bytes,
        filename: str,
        objective_sense_override: ObjectiveSense | None = None,
    ) -> OptimizationProblem:
        """Import an optimization problem from a file.

        Args:
            file_bytes: Raw file content.
            filename: Original filename (used to detect format).
            objective_sense_override: Override the objective sense from the file.

        Returns:
            OptimizationProblem ready for solving.

        Raises:
            FileImportError: If the file cannot be parsed or is invalid.
        """
        extension = validate_extension(filename)

        if extension == ".json":
            if len(file_bytes) > MAX_JSON_SIZE:
                raise FileImportError(
                    f"JSON file too large: {len(file_bytes)} bytes "
                    f"(max {MAX_JSON_SIZE // (1024 * 1024)} MB)"
                )
            return self._import_json(file_bytes)

        if len(file_bytes) > MAX_IMPORT_SIZE:
            raise FileImportError(
                f"File too large: {len(file_bytes)} bytes "
                f"(max {MAX_IMPORT_SIZE // (1024 * 1024)} MB)"
            )

        tmp_path = self._save_upload_to_temp(file_bytes, extension)
        try:
            model = self._read_via_scip(tmp_path, extension)
            return self._extract_problem(model, objective_sense_override)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.debug("Failed to clean up temp file: %s", tmp_path)

    def _save_upload_to_temp(self, file_bytes: bytes, extension: str) -> str:
        """Save uploaded bytes to a temp file for SCIP to read.

        For .gz files, decompresses first and saves with the inner extension.
        Decompression is streamed with a hard cap of ``MAX_IMPORT_SIZE`` bytes
        to block gzip bomb attacks (tiny compressed file that inflates to
        gigabytes).

        Returns:
            Path to the temporary file.
        """
        if extension.endswith(".gz"):
            try:
                file_bytes = self._safe_gzip_decompress(file_bytes, MAX_IMPORT_SIZE)
            except (gzip.BadGzipFile, OSError) as exc:
                raise FileImportError(f"Failed to decompress gzip file: {exc}") from exc
            # Use inner extension (.mps or .lp) for the temp file
            inner_ext = extension.replace(".gz", "")
        else:
            inner_ext = extension

        fd, tmp_path = tempfile.mkstemp(suffix=inner_ext)
        try:
            os.write(fd, file_bytes)
        finally:
            os.close(fd)

        return tmp_path

    @staticmethod
    def _safe_gzip_decompress(file_bytes: bytes, max_bytes: int) -> bytes:
        """Decompress gzip content while capping the output to *max_bytes*.

        Reads in 64 KiB chunks and raises :class:`FileImportError` as soon as
        the running total would exceed the cap. This prevents an attacker
        from uploading a tiny compressed file that explodes to gigabytes and
        exhausts memory.
        """
        chunk_size = 64 * 1024
        buffer = bytearray()
        with gzip.GzipFile(fileobj=io.BytesIO(file_bytes), mode="rb") as gz:
            while True:
                chunk = gz.read(chunk_size)
                if not chunk:
                    break
                if len(buffer) + len(chunk) > max_bytes:
                    raise FileImportError(
                        f"Decompressed content exceeds {max_bytes // (1024 * 1024)} MB "
                        "limit (gzip bomb suspected)."
                    )
                buffer.extend(chunk)
        return bytes(buffer)

    def _read_via_scip(self, tmp_path: str, extension: str) -> Model:
        """Read a model file using SCIP's readProblem.

        Args:
            tmp_path: Path to the temporary file.
            extension: File extension (for logging).

        Returns:
            SCIP Model loaded from the file.

        Raises:
            FileImportError: If SCIP cannot read the file.
        """
        try:
            model = Model("imported_problem")
            model.hideOutput()
            model.setParam("display/verblevel", 0)
            model.readProblem(tmp_path)
            logger.info(
                "SCIP loaded file: %d vars, %d conss",
                model.getNVars(),
                model.getNConss(),
            )
            return model
        except Exception as exc:
            raise FileImportError(f"SCIP failed to read file: {exc}") from exc

    def _extract_problem(
        self,
        model: Model,
        sense_override: ObjectiveSense | None,
    ) -> OptimizationProblem:
        """Extract an OptimizationProblem from a loaded SCIP model.

        Args:
            model: SCIP Model loaded from a file.
            sense_override: Optional override for the objective sense.

        Returns:
            OptimizationProblem populated from the SCIP model.
        """
        variables = self._extract_variables(model)
        if not variables:
            raise FileImportError("No variables found in model file")

        objective = self._extract_objective(model, sense_override)
        constraints = self._extract_constraints(model)

        problem_name = model.getProbName() or "imported_problem"
        sanitized_name = _sanitize_var_name(problem_name)

        return OptimizationProblem(
            name=sanitized_name,
            description=f"Imported from file ({len(variables)} variables, "
            f"{len(constraints)} constraints)",
            variables=variables,
            objective=objective,
            constraints=constraints,
        )

    def _extract_variables(self, model: Model) -> list[Variable]:
        """Extract variables from SCIP model.

        Maps SCIP variable types (BINARY, INTEGER, CONTINUOUS, IMPLINT)
        to JAOT VariableType. Sanitizes names for compatibility.
        """
        variables: list[Variable] = []
        seen_names: set[str] = set()

        for scip_var in model.getVars():
            raw_name = scip_var.name
            name = _sanitize_var_name(raw_name)

            # Ensure uniqueness after sanitization
            if name in seen_names:
                counter = 1
                while f"{name}_{counter}" in seen_names:
                    counter += 1
                name = f"{name}_{counter}"
            seen_names.add(name)

            vtype_str = scip_var.vtype()
            var_type = _SCIP_VTYPE_MAP.get(vtype_str, VariableType.CONTINUOUS)

            lb = scip_var.getLbOriginal()
            ub = scip_var.getUbOriginal()

            # Convert SCIP infinity to None
            lb_val = lb if lb > -1e19 else None
            ub_val = ub if ub < 1e19 else None

            variables.append(
                Variable(
                    name=name,
                    type=var_type,
                    lower_bound=lb_val,
                    upper_bound=ub_val,
                )
            )

        return variables

    def _extract_objective(
        self,
        model: Model,
        sense_override: ObjectiveSense | None,
    ) -> Objective:
        """Extract the objective function from SCIP model.

        Builds a string expression from variable objective coefficients.
        """
        if sense_override is not None:
            sense = sense_override
        else:
            scip_sense = model.getObjectiveSense()
            sense = ObjectiveSense.MINIMIZE if scip_sense == "minimize" else ObjectiveSense.MAXIMIZE

        terms: list[str] = []
        for scip_var in model.getVars():
            coeff = scip_var.getObj()
            if abs(coeff) < 1e-12:
                continue

            name = _sanitize_var_name(scip_var.name)

            if coeff == 1.0:
                terms.append(name)
            elif coeff == -1.0:
                terms.append(f"-{name}")
            else:
                terms.append(f"{coeff}*{name}")

        expression = " + ".join(terms) if terms else "0"
        # Clean up "+ -" to "- "
        expression = expression.replace("+ -", "- ")

        return Objective(sense=sense, expression=expression)

    def _extract_constraints(self, model: Model) -> list[Constraint]:
        """Extract constraints, trying linear extraction first, CIP fallback."""
        constraints = self._extract_constraints_linear(model)
        if constraints:
            return constraints

        logger.info("Linear extraction yielded no constraints, trying CIP fallback")
        return self._extract_constraints_via_cip(model)

    def _extract_constraints_linear(self, model: Model) -> list[Constraint]:
        """Extract constraints via SCIP's getValsLinear (fast path).

        Works for linear constraints. Returns empty list if any constraint
        fails, signaling the caller to try the CIP fallback.
        """
        constraints: list[Constraint] = []

        for scip_cons in model.getConss():
            try:
                vals = model.getValsLinear(scip_cons)
            except Exception:
                logger.debug(
                    "getValsLinear failed for constraint %s, will use CIP fallback",
                    scip_cons.name,
                )
                return []

            if not vals:
                continue

            terms: list[str] = []
            for var_ref, coeff in vals.items():
                if abs(coeff) < 1e-12:
                    continue
                var_name = var_ref.name if hasattr(var_ref, "name") else str(var_ref)
                name = _sanitize_var_name(var_name)
                if coeff == 1.0:
                    terms.append(name)
                elif coeff == -1.0:
                    terms.append(f"-{name}")
                else:
                    terms.append(f"{coeff}*{name}")

            if not terms:
                continue

            lhs = " + ".join(terms).replace("+ -", "- ")

            lhs_bound = model.getLhs(scip_cons)
            rhs_bound = model.getRhs(scip_cons)

            has_lhs = lhs_bound is not None and lhs_bound > -1e19
            has_rhs = rhs_bound is not None and rhs_bound < 1e19

            raw_name = scip_cons.name
            cons_name = _sanitize_var_name(raw_name) if raw_name else None

            if has_lhs and has_rhs and abs(lhs_bound - rhs_bound) < 1e-12:
                # Equality constraint
                constraints.append(
                    Constraint(
                        name=cons_name,
                        expression=f"{lhs} == {rhs_bound}",
                    )
                )
            else:
                if has_rhs:
                    constraints.append(
                        Constraint(
                            name=cons_name,
                            expression=f"{lhs} <= {rhs_bound}",
                        )
                    )
                if has_lhs:
                    suffix = "_lb" if has_rhs else ""
                    lb_name = f"{cons_name}{suffix}" if cons_name else None
                    constraints.append(
                        Constraint(
                            name=lb_name,
                            expression=f"{lhs} >= {lhs_bound}",
                        )
                    )

        return constraints

    def _extract_constraints_via_cip(self, model: Model) -> list[Constraint]:
        """Extract constraints by writing model to CIP and parsing.

        Fallback when getValsLinear fails (non-linear constraints, etc.).
        """
        fd, cip_path = tempfile.mkstemp(suffix=".cip")
        os.close(fd)

        try:
            model.writeProblem(cip_path)
            return parse_cip_constraints(cip_path)
        except Exception as exc:
            logger.warning("CIP fallback failed: %s", exc)
            return []
        finally:
            try:
                os.unlink(cip_path)
            except OSError:
                pass

    def _import_json(self, file_bytes: bytes) -> OptimizationProblem:
        """Import a problem from JAOT JSON format.

        Validates the JSON against the OptimizationProblem schema directly.
        Rejects pathologically deep payloads BEFORE parsing (a cheap DoS
        vector) by scanning bracket depth, which does not depend on the
        Python stack size and is portable across CPython builds.
        """
        self._check_json_depth(file_bytes, MAX_JSON_DEPTH)

        try:
            data = json.loads(file_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise FileImportError(f"Invalid JSON: {exc}") from exc
        except RecursionError as exc:
            raise FileImportError("Invalid JSON: nesting depth exceeds server limit") from exc

        if not isinstance(data, dict):
            raise FileImportError("JSON root must be an object")

        # Tolerate the wrapped execution-export shape {"problem": ..., "result": ...}.
        # "Export model" emits a flat OptimizationProblem, but execution exports
        # (and "export result") wrap it under "problem". A flat problem always
        # carries "variables" at the top level, so unwrapping only the wrapped
        # shape is unambiguous and makes the export->import round-trip work.
        if "variables" not in data and isinstance(data.get("problem"), dict):
            data = data["problem"]

        try:
            return OptimizationProblem(**data)
        except Exception as exc:
            raise FileImportError(f"JSON does not match OptimizationProblem schema: {exc}") from exc

    @staticmethod
    def _check_json_depth(file_bytes: bytes, max_depth: int) -> None:
        """Reject the payload if its nesting depth exceeds *max_depth*.

        Scans the raw bytes counting unescaped ``{`` / ``[`` openings while
        tracking string-literal state so brackets inside string values do
        not inflate the counter. Bails early as soon as the cap is crossed.
        This is a pre-parse guard against stack-exhaustion DoS payloads and
        does not rely on Python's recursion limit, which varies by build.
        """
        depth = 0
        in_string = False
        escape = False
        QUOTE = 0x22  # "
        BACKSLASH = 0x5C  # \
        OPEN_BRACE = 0x7B  # {
        OPEN_BRACKET = 0x5B  # [
        CLOSE_BRACE = 0x7D  # }
        CLOSE_BRACKET = 0x5D  # ]
        for b in file_bytes:
            if escape:
                escape = False
                continue
            if in_string:
                if b == BACKSLASH:
                    escape = True
                elif b == QUOTE:
                    in_string = False
                continue
            if b == QUOTE:
                in_string = True
            elif b == OPEN_BRACE or b == OPEN_BRACKET:
                depth += 1
                if depth > max_depth:
                    raise FileImportError(f"Invalid JSON: nesting depth exceeds {max_depth} limit")
            elif b == CLOSE_BRACE or b == CLOSE_BRACKET:
                depth -= 1


# Singleton
_file_import_service: FileImportService | None = None


def get_file_import_service() -> FileImportService:
    """Get or create FileImportService singleton."""
    global _file_import_service
    if _file_import_service is None:
        _file_import_service = FileImportService()
    return _file_import_service
