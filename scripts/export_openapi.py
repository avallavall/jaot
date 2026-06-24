#!/usr/bin/env python3
"""Export FastAPI OpenAPI schema to openapi.json.

Usage:
    python scripts/export_openapi.py

Produces a deterministic openapi.json at the repository root by calling
app.openapi() on the FastAPI instance. No running server required.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "openapi.json"

schema = app.openapi()
content = json.dumps(schema, indent=2, sort_keys=True) + "\n"
OUTPUT.write_text(content, encoding="utf-8")

print(f"OpenAPI schema exported to {OUTPUT} ({len(content)} bytes)")
