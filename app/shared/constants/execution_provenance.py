"""Where a solve came from: its creation channel and the object behind it.

A platform concern, deliberately kept OUT of the solver-agnostic
``OptimizationProblem``/``OptimizationResult`` schemas — a solver has no opinion
on whether a model arrived from the visual builder or an imported file.

It lives in ``app/shared/`` rather than beside the solve helpers because both
sides need it and neither owns it: the API records provenance when it enqueues,
and the solver domain's own routes label the solves they start. Importing it
from a service module made those routes depend upward on the platform for two
string constants (D-16).

Persisted on ``ModelExecution.origin`` / ``source_kind`` / ``source_id`` — see
the ``20260628_exec_provenance`` migration.
"""

from dataclasses import dataclass

ORIGIN_MANUAL = "manual"
ORIGIN_VISUAL_BUILDER = "visual_builder"
ORIGIN_AI_BUILDER = "ai_builder"
ORIGIN_TEMPLATE = "template"
ORIGIN_IMPORT = "import"
ORIGIN_MARKETPLACE = "marketplace"
# "triggered" (not "trigger") to match the value triggers already write — avoids
# splitting historical rows across two slugs.
ORIGIN_TRIGGER = "triggered"
ORIGIN_API = "api"
ORIGIN_MCP = "mcp"
# One column of a solver comparison. Its own origin because a comparison writes
# one execution per solver: four rows land in the org's history for a single
# thing the user did, and without a label there is no way to tell them apart from
# four separate solves the user ran on purpose.
ORIGIN_COMPARISON = "comparison"

VALID_ORIGINS = frozenset(
    {
        ORIGIN_MANUAL,
        ORIGIN_VISUAL_BUILDER,
        ORIGIN_AI_BUILDER,
        ORIGIN_TEMPLATE,
        ORIGIN_IMPORT,
        ORIGIN_MARKETPLACE,
        ORIGIN_TRIGGER,
        ORIGIN_API,
        ORIGIN_MCP,
        ORIGIN_COMPARISON,
    }
)

# The object an execution can navigate back to. Generic (not FKs) because
# builder_document / llm_conversation / template have no FK on model_executions.
VALID_SOURCE_KINDS = frozenset(
    {
        "builder_document",
        "llm_conversation",
        "template",
        "organization_model",
        "trigger",
        "imported_file",
        # P1a: a solve launched from a first-class ModelProject. Code-only addition
        # — the source_kind column is already VARCHAR(32), so no DB change is needed.
        "model_project",
    }
)

_SOURCE_ID_MAX_LEN = 64  # matches ModelExecution.source_id column width


@dataclass(frozen=True)
class ExecutionSource:
    """Provenance of a solve: its creation channel and the object it came from.

    ``origin`` is the channel (``visual_builder``, ``ai_builder``, ``template``…).
    ``source_kind``/``source_id`` point at the object the execution can navigate
    back to. All fields default so callers without provenance fall back to a
    plain manual solve.
    """

    origin: str = ORIGIN_MANUAL
    source_kind: str | None = None
    source_id: str | None = None

    @classmethod
    def from_request(
        cls,
        origin: str | None,
        source_kind: str | None = None,
        source_id: str | None = None,
    ) -> "ExecutionSource":
        """Build from untrusted query params, sanitising unknown values.

        Unknown origins collapse to ``manual`` and unknown source kinds to
        ``None`` so a client cannot write arbitrary strings into the executions
        table; ``source_id`` is dropped when there is no valid kind and capped
        to the column width.
        """
        clean_origin = origin if origin in VALID_ORIGINS else ORIGIN_MANUAL
        clean_kind = source_kind if source_kind in VALID_SOURCE_KINDS else None
        clean_id = None
        if clean_kind and source_id:
            clean_id = source_id[:_SOURCE_ID_MAX_LEN]
        return cls(origin=clean_origin, source_kind=clean_kind, source_id=clean_id)
