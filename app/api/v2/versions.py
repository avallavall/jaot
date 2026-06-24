"""Version history endpoints for builder documents.

Mounted by builder.py at /{document_id}/versions so all routes here
are relative to that prefix (e.g. GET / lists versions for a document).

Import deps from app.api.deps (NOT app.api.v2.deps).
"""

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import desc

from app.api.deps import CurrentOrg, CurrentUser, DBSession
from app.api.v2.builder import _get_doc_or_404
from app.models.model_version import ModelVersion
from app.schemas.version import (
    CreateCheckpointRequest,
    ModelVersionListItem,
    ModelVersionResponse,
    PromoteVersionRequest,
    RestoreRequest,
    RestoreResponse,
)
from app.services import version_service

logger = logging.getLogger(__name__)

# No prefix — builder.py mounts this at /{document_id}/versions
router = APIRouter(tags=["versions"])


def _get_version_or_404(
    db: DBSession,
    version_id: str,
    document_id: str,
    org_id: str,
) -> ModelVersion:
    """Fetch a version with full ownership validation or raise 404."""
    version = version_service.get_version(db, version_id, document_id, org_id)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )
    return version


@router.get(
    "/",
    response_model=list[ModelVersionListItem],
    summary="List versions for a builder document",
)
def list_versions(
    document_id: str,
    db: DBSession,
    org: CurrentOrg,
    skip: int = 0,
    limit: int = 50,
) -> list[ModelVersion]:
    """Return version list for a document (newest first, no canvas_json)."""
    _get_doc_or_404(db, document_id, org.id)
    return version_service.list_versions(db, document_id, org.id, limit=limit, skip=skip)


@router.get(
    "/{version_id}",
    response_model=ModelVersionResponse,
    summary="Get a single version with full canvas_json",
)
def get_version(
    document_id: str,
    version_id: str,
    db: DBSession,
    org: CurrentOrg,
) -> ModelVersion:
    """Return a single version including the full canvas_json snapshot."""
    _get_doc_or_404(db, document_id, org.id)
    return _get_version_or_404(db, version_id, document_id, org.id)


@router.post(
    "/",
    response_model=ModelVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an unnamed version checkpoint",
)
def create_checkpoint(
    document_id: str,
    body: CreateCheckpointRequest,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> ModelVersion:
    """Snapshot the current canvas as an unnamed checkpoint.

    If the canvas is unchanged since the last checkpoint, the existing version
    is returned (201 status, no duplicate row created).
    """
    doc = _get_doc_or_404(db, document_id, org.id)

    # Fetch the latest version to compute the change summary
    prev = (
        db.query(ModelVersion)
        .filter(ModelVersion.document_id == document_id)
        .order_by(desc(ModelVersion.sequence))
        .first()
    )
    prev_canvas = prev.canvas_json if prev else None

    version = version_service.create_checkpoint(
        db,
        doc,
        body.canvas_json,
        prev_canvas,
        model_json=doc.model_json,
    )
    db.commit()
    logger.info("Checkpoint %s created for document %s by user %s", version.id, doc.id, user.id)
    return version


@router.patch(
    "/{version_id}",
    response_model=ModelVersionResponse,
    summary="Promote a checkpoint to a named version",
)
def promote_version(
    document_id: str,
    version_id: str,
    body: PromoteVersionRequest,
    db: DBSession,
    org: CurrentOrg,
) -> ModelVersion:
    """Assign a name (and optional description) to an existing checkpoint.

    Named versions are never pruned by the retention policy.
    """
    _get_doc_or_404(db, document_id, org.id)
    version = _get_version_or_404(db, version_id, document_id, org.id)
    updated = version_service.promote_to_named(
        db, version, body.version_name, body.version_description
    )
    db.commit()
    return updated


@router.post(
    "/{version_id}/restore",
    response_model=RestoreResponse,
    summary="Restore the document to a previous version",
)
def restore_version(
    document_id: str,
    version_id: str,
    body: RestoreRequest,
    db: DBSession,
    org: CurrentOrg,
) -> RestoreResponse:
    """Restore the document canvas to the target version.

    Before applying the restore, the service auto-checkpoints the current
    canvas so the user can undo the restore if needed.

    Returns the ID of the safety checkpoint and the updated document.
    """
    doc = _get_doc_or_404(db, document_id, org.id)
    target = _get_version_or_404(db, version_id, document_id, org.id)

    safety_checkpoint, updated_doc = version_service.restore_version(
        db, doc, target, body.current_canvas_json
    )
    db.commit()

    return RestoreResponse(
        checkpoint_id=safety_checkpoint.id,
        document={
            "id": updated_doc.id,
            "organization_id": updated_doc.organization_id,
            "name": updated_doc.name,
            "canvas_json": updated_doc.canvas_json,
            "model_json": updated_doc.model_json,
            "is_active": updated_doc.is_active,
            "created_at": updated_doc.created_at.isoformat(),
            "updated_at": updated_doc.updated_at.isoformat(),
        },
    )
