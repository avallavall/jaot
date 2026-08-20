"""List routes that touch a walled table without asking the workspace wall.

A workspace is a wall, not a folder (see
``docs/ARCHITECTURE/02-backend/04-patterns.md`` §7): a caller who is not a
member of the workspace a row is filed in must reach nothing of it, not through
a list and not by a direct id. Filtering by ``organization_id`` is not enough.

Three sweeps of that wall in one day closed 25 holes. Two of them were found by
this shape check rather than by driving the app, so it is kept as a helper: run
it after adding a route that loads a project, a run, a trigger, a schedule or a
comparison.

    python scripts/audit_workspace_wall.py

It prints candidates, not defects. Read each one before believing it:

- Routes under ``app/api/v2/routes/admin/`` are correct as they are. A platform
  administrator is not held by a tenant's workspace.
- A route that only creates a row has no row to be walled yet.
- ``llm.py:list_conversations`` filters by ``user_id`` as well, so it only ever
  lists the caller's own conversations (checked 2026-08-20).
- ``profiles/reviews.py:create_review`` is about a marketplace listing, which is
  public by design; its gates are the author's own organization and having run
  the model (checked 2026-08-20).

It also cannot see a guard that has been re-implemented privately. Two modules
kept their own ``_project_or_404`` with no wall in it, and this script counted
the name as proof. If a route names a loader, open the loader.

Exit code is 0 whatever it finds: this reports, it does not gate.
"""

from __future__ import annotations

import io
import os
import re
import sys

#: Tables whose rows can sit behind a workspace, directly or through a project.
WALLED_TABLES = (
    "SolveTrigger",
    "TriggerSchedule",
    "ModelProject",
    "ModelExecution",
    "SolverComparison",
    "ModelProjectDataset",
    "ModelProjectVersion",
)

#: Names that mean the wall was asked, either here or inside what this calls.
GUARDS = (
    "enforce_workspace_of",
    "enforce_execution_workspace",
    "workspace_ids_open_to",
    "check_workspace_role",
    "OptionalRequire",
    "_project_or_404",
    "_writable_project_or_404",
    "_get_trigger_or_404",
    "_comparison_or_404",
    "_resolve_problem",
    "_members_or_404",
    "_batch_detail",
    "execution_or_404",
    "load_execution",
)

_ROUTE_SPLIT = re.compile(r"\n(?=@router\.)")
_DEF = re.compile(r"\ndef (\w+)\(")
_PATH = re.compile(r'"(/[^"]*)"')


def _candidates(root: str = "app") -> list[tuple[str, str, str, list[str]]]:
    found: list[tuple[str, str, str, list[str]]] = []
    for folder, _, files in os.walk(root):
        if "__pycache__" in folder:
            continue
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name).replace(os.sep, "/")
            source = io.open(path, encoding="utf-8").read()
            if "@router." not in source:
                continue
            for block in _ROUTE_SPLIT.split(source):
                if not block.startswith("@router."):
                    continue
                handler = _DEF.search("\n" + block)
                if handler is None:
                    continue
                touches = [t for t in WALLED_TABLES if re.search(r"\b" + t + r"\b", block)]
                if not touches or "organization_id" not in block:
                    continue
                if any(g in block for g in GUARDS):
                    continue
                route = _PATH.search(block)
                found.append((path, handler.group(1), route.group(1) if route else "", touches))
    return found


def main() -> int:
    rows = _candidates()
    for path, handler, route, touches in rows:
        print(f"{path}:{handler}")
        print(f"    {route or '(no literal path)'}  touches {', '.join(touches)}")
    print()
    print(f"{len(rows)} route(s) touch a walled table with no wall guard in sight")
    return 0


if __name__ == "__main__":
    sys.exit(main())
