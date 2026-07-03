"""Parse an uploaded data file into the dataset ``data_json`` shape (S2c).

Three formats, inferred from the file extension:

* ``.dat``  — AMPL data subset (``app.domains.dsl.dat_parser``).
* ``.json`` — our native shape (``{"sets": {...}, "params": {...}}``).
* ``.csv``  — ONE param per file: columns ``index1..indexN,value`` (an optional
  header row is skipped when its last cell is not a number). The param name
  defaults from the filename and is caller-overridable.

Model formats (MPS/LP/CIP) are deliberately NOT here: they are already-grounded
matrices with no extractable data part. XLSX is deferred.

The parsed result is a PREVIEW — the route returns it for the user to name and
save through the normal dataset create, which re-validates (size cap + shape).
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from app.domains.dsl import JModelError
from app.domains.dsl.dat_parser import parse_dat

SUPPORTED_EXTENSIONS = (".dat", ".json", ".csv")

_NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_NAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]+")


def _file_stem(filename: str) -> str:
    """The bare stem of an (untrusted) uploaded filename, both separators handled."""
    stem = PurePosixPath(PureWindowsPath(filename).as_posix()).stem
    return _NAME_SANITIZE_RE.sub("_", stem).strip("_") or "value"


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")  # tolerate a BOM (Excel CSV exports)
    except UnicodeDecodeError as exc:
        raise JModelError("file is not valid UTF-8 text") from exc


def _parse_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JModelError(f"invalid JSON: {exc.msg}", position=exc.pos) from exc
    if not isinstance(data, dict):
        raise JModelError("dataset JSON must be an object with 'sets' and/or 'params'")
    return data


def _parse_csv(text: str, param_name: str) -> dict[str, Any]:
    """One param per file: ``index1..indexN,value`` rows, optional header."""
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        raise JModelError("CSV file has no rows")
    # Header heuristic: a first row whose LAST cell is not a number is labels.
    if rows and not _NUM_RE.match(rows[0][-1].strip()):
        rows = rows[1:]
        if not rows:
            raise JModelError("CSV file has a header but no data rows")

    arity = len(rows[0]) - 1
    if arity < 1:
        raise JModelError("CSV rows need at least 2 columns: index1..indexN, value")
    values: dict[str, float] = {}
    for line_no, row in enumerate(rows, start=1):
        cells = [cell.strip() for cell in row]
        if len(cells) != arity + 1:
            raise JModelError(
                f"CSV row {line_no} has {len(cells)} columns — expected {arity + 1} "
                f"(index1..index{arity}, value)"
            )
        raw_value = cells[-1]
        if not _NUM_RE.match(raw_value):
            raise JModelError(f"CSV row {line_no} value {raw_value!r} is not a number")
        key_parts = cells[:-1]
        if any(not part for part in key_parts):
            raise JModelError(f"CSV row {line_no} has an empty index cell")
        key = ",".join(key_parts)
        if key in values:
            raise JModelError(f"CSV row {line_no} repeats the key {key!r}")
        values[key] = float(raw_value)
    return {"params": {param_name: values}}


def parse_dataset_file(
    filename: str, content: bytes, param_name: str | None = None
) -> tuple[dict[str, Any], str]:
    """Parse an uploaded file into ``(data_json, suggested_dataset_name)``.

    Raises :class:`JModelError` on an unsupported extension or any parse error
    (message + character position when known). The caller still runs the normal
    dataset validation before storing anything.
    """
    lower = filename.lower()
    suggested = _file_stem(filename)
    if lower.endswith(".dat"):
        return parse_dat(_decode(content)), suggested
    if lower.endswith(".json"):
        return _parse_json(_decode(content)), suggested
    if lower.endswith(".csv"):
        name = (param_name or "").strip() or _file_stem(filename)
        return _parse_csv(_decode(content), name), suggested
    raise JModelError("unsupported file type — use .dat (AMPL data), .json (dataset shape) or .csv")
