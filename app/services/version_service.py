"""Version service — snapshot, prune, promote, and restore builder document versions.

All functions accept a SQLAlchemy Session directly and have no FastAPI context,
following the same pattern as invoice_service.py.
"""

import logging
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# Maximum number of unnamed checkpoints retained per document.
_MAX_UNNAMED = 50


def compute_change_summary(prev_canvas: dict[str, Any] | None, new_canvas: dict[str, Any]) -> str:
    """Compare two canvas states and return a human-readable change description.

    Compares node lists by ID to detect added, removed, and modified nodes.
    Modifications are detected by comparing the serialised node content.

    Returns:
        "Initial version"        — when prev_canvas is None
        "No changes"             — when the canvas is byte-for-byte identical
        "Added X, Y; Removed Z"  — descriptive summary otherwise
    """
    if prev_canvas is None:
        return "Initial version"

    prev_nodes: dict[str, dict[str, Any]] = {
        n["id"]: n for n in (prev_canvas.get("nodes") or []) if "id" in n
    }
    new_nodes: dict[str, dict[str, Any]] = {
        n["id"]: n for n in (new_canvas.get("nodes") or []) if "id" in n
    }

    added = [nid for nid in new_nodes if nid not in prev_nodes]
    removed = [nid for nid in prev_nodes if nid not in new_nodes]
    modified = [nid for nid in new_nodes if nid in prev_nodes and new_nodes[nid] != prev_nodes[nid]]

    if not added and not removed and not modified:
        return "No changes"

    parts: list[str] = []
    if added:
        labels = [new_nodes[nid].get("data", {}).get("label", nid) for nid in added]
        parts.append(f"Added {', '.join(labels)}")
    if removed:
        labels = [prev_nodes[nid].get("data", {}).get("label", nid) for nid in removed]
        parts.append(f"Removed {', '.join(labels)}")
    if modified:
        labels = [new_nodes[nid].get("data", {}).get("label", nid) for nid in modified]
        parts.append(f"Modified {', '.join(labels)}")

    summary = "; ".join(parts)
    # Truncate to 500 chars (column limit) with ellipsis
    if len(summary) > 497:
        summary = summary[:497] + "..."
    return summary


def _prune_unnamed(db: Session, document_id: str) -> None:
    """Delete the oldest unnamed checkpoints that exceed the retention limit.

    CRITICAL: Only unnamed checkpoints (is_named=False) are eligible for
    pruning. Named versions are never touched.
    """
    # Fetch ALL unnamed checkpoints for this document, newest first
    unnamed = (
        db.query(ModelVersion)
        .filter(
            ModelVersion.document_id == document_id,
            ModelVersion.is_named.is_(False),
        )
        .order_by(desc(ModelVersion.sequence))
        .all()
    )

    excess = unnamed[_MAX_UNNAMED:]
    if excess:
        excess_ids = [v.id for v in excess]
        db.query(ModelVersion).filter(ModelVersion.id.in_(excess_ids)).delete(
            synchronize_session="fetch"
        )
        logger.debug("Pruned %d unnamed checkpoints for document %s", len(excess_ids), document_id)


def _next_sequence(db: Session, document_id: str) -> int:
    """Return the next sequence number for a document (MAX + 1, or 1 if none)."""
    result = (
        db.query(func.max(ModelVersion.sequence))
        .filter(ModelVersion.document_id == document_id)
        .scalar()
    )
    return (result or 0) + 1


def create_checkpoint(
    db: Session,
    document: ModelBuilderDocument,
    canvas_json: dict[str, Any],
    prev_canvas_json: dict[str, Any] | None,
    model_json: dict[str, Any] | None = None,
) -> ModelVersion:
    """Create an unnamed version checkpoint for a document.

    If canvas_json is identical to prev_canvas_json (same nodes by ID and
    content), no new row is created; the latest existing version is returned
    instead to avoid duplicate snapshots.

    After inserting the new version, unnamed checkpoints exceeding
    _MAX_UNNAMED are pruned (oldest first).

    Args:
        db: Database session.
        document: The owning ModelBuilderDocument.
        canvas_json: New canvas state to snapshot.
        prev_canvas_json: Previous canvas state used for change summary
            computation (None for the first checkpoint).

    Returns:
        The newly created ModelVersion, or the latest existing version if
        the canvas was unchanged.
    """
    # Skip if canvas is identical to the previous snapshot
    if prev_canvas_json is not None:
        prev_nodes = {n["id"]: n for n in (prev_canvas_json.get("nodes") or []) if "id" in n}
        new_nodes = {n["id"]: n for n in (canvas_json.get("nodes") or []) if "id" in n}
        if prev_nodes == new_nodes:
            existing = (
                db.query(ModelVersion)
                .filter(ModelVersion.document_id == document.id)
                .order_by(desc(ModelVersion.sequence))
                .first()
            )
            if existing is not None:
                return existing

    summary = compute_change_summary(prev_canvas_json, canvas_json)
    seq = _next_sequence(db, document.id)

    version = ModelVersion(
        id=generate_id("ver_"),
        document_id=document.id,
        organization_id=document.organization_id,
        canvas_json=canvas_json,
        model_json=model_json,
        change_summary=summary,
        is_named=False,
        version_name=None,
        version_description=None,
        sequence=seq,
        created_at=utcnow(),
    )
    db.add(version)
    db.flush()  # assign PK before pruning query

    _prune_unnamed(db, document.id)
    db.flush()
    db.refresh(version)

    logger.info("Created checkpoint %s (seq=%d) for document %s", version.id, seq, document.id)
    return version


def promote_to_named(
    db: Session,
    version: ModelVersion,
    name: str,
    description: str | None = None,
) -> ModelVersion:
    """Promote an unnamed checkpoint to a named version.

    Named versions are excluded from pruning and persist indefinitely.

    Args:
        db: Database session.
        version: The ModelVersion to promote.
        name: Human-readable name for the version.
        description: Optional longer description.

    Returns:
        The updated ModelVersion with is_named=True.
    """
    version.is_named = True
    version.version_name = name
    version.version_description = description
    db.flush()
    db.refresh(version)
    return version


def restore_version(
    db: Session,
    document: ModelBuilderDocument,
    target_version: ModelVersion,
    current_canvas_json: dict[str, Any],
) -> tuple[ModelVersion, ModelBuilderDocument]:
    """Restore a document to a previous version.

    Safety protocol:
    1. Create an unnamed checkpoint of the *current* canvas state so the
       user can recover if the restore was a mistake.
    2. Overwrite document.canvas_json with the target version's canvas_json.
    3. Update document.updated_at.

    Args:
        db: Database session.
        document: The ModelBuilderDocument to restore.
        target_version: The version to restore to.
        current_canvas_json: The caller's current canvas state (for safety snapshot).

    Returns:
        Tuple of (safety_checkpoint, updated_document).
    """
    # Step 1: Safety snapshot of the current state
    prev_latest = (
        db.query(ModelVersion)
        .filter(ModelVersion.document_id == document.id)
        .order_by(desc(ModelVersion.sequence))
        .first()
    )
    prev_canvas = prev_latest.canvas_json if prev_latest else None

    safety_checkpoint = create_checkpoint(
        db,
        document,
        current_canvas_json,
        prev_canvas,
        model_json=document.model_json,
    )

    # Step 2: Apply the target version's canvas and model
    document.canvas_json = target_version.canvas_json
    document.model_json = target_version.model_json
    document.updated_at = utcnow()
    db.flush()
    db.refresh(document)

    logger.info(
        "Restored document %s to version %s; safety checkpoint %s created",
        document.id,
        target_version.id,
        safety_checkpoint.id,
    )
    return safety_checkpoint, document


def list_versions(
    db: Session,
    document_id: str,
    org_id: str,
    limit: int = 50,
    skip: int = 0,
) -> list[ModelVersion]:
    """Return versions for a document, newest first.

    Args:
        db: Database session.
        document_id: The document whose versions to list.
        org_id: Organization ownership guard.
        limit: Maximum number of versions to return.
        skip: Number of versions to skip (for pagination).

    Returns:
        List of ModelVersion objects ordered by sequence descending.
    """
    return (
        db.query(ModelVersion)
        .filter(
            ModelVersion.document_id == document_id,
            ModelVersion.organization_id == org_id,
        )
        .order_by(desc(ModelVersion.sequence))
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_version(
    db: Session,
    version_id: str,
    document_id: str,
    org_id: str,
) -> ModelVersion | None:
    """Fetch a single version with ownership validation.

    Args:
        db: Database session.
        version_id: Primary key of the ModelVersion.
        document_id: Expected document owner.
        org_id: Expected organisation owner.

    Returns:
        ModelVersion if found and owned, None otherwise.
    """
    return (
        db.query(ModelVersion)
        .filter(
            ModelVersion.id == version_id,
            ModelVersion.document_id == document_id,
            ModelVersion.organization_id == org_id,
        )
        .first()
    )
