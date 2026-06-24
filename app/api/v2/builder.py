"""Builder CRUD endpoints — create, read, update, delete visual model builder documents."""

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import desc

from app.api.deps import (
    CurrentOrg,
    CurrentUser,
    DBSession,
    OptionalRequireEditor,
    OptionalRequireSolver,
    OptionalRequireViewer,
)
from app.models.audit_log import AuditAction
from app.models.builder_document import ModelBuilderDocument
from app.schemas.builder import (
    BuilderDocumentCreate,
    BuilderDocumentListResponse,
    BuilderDocumentResponse,
    BuilderDocumentUpdate,
)
from app.services.audit_service import log_action
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/builder", tags=["builder"])


def _get_doc_or_404(
    db: DBSession,
    document_id: str,
    org_id: str,
) -> ModelBuilderDocument:
    """Fetch an active document owned by the org or raise 404."""
    doc = (
        db.query(ModelBuilderDocument)
        .filter(
            ModelBuilderDocument.id == document_id,
            ModelBuilderDocument.organization_id == org_id,
            ModelBuilderDocument.is_active.is_(True),
        )
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Builder document not found",
        )
    return doc


@router.post(
    "/",
    response_model=BuilderDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new builder document",
)
def create_document(
    body: BuilderDocumentCreate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireSolver,
) -> ModelBuilderDocument:
    """Create a new visual model builder document for the current organization."""
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=org.id,
        created_by=user.id,
        name=body.name,
        canvas_json={},
        model_json=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_EDIT,
        target_type="builder_document",
        target_id=doc.id,
        target_name=body.name,
    )
    db.commit()
    db.refresh(doc)
    logger.info("Created builder document %s for org %s", doc.id, org.id)
    return doc


@router.get(
    "/",
    response_model=list[BuilderDocumentListResponse],
    summary="List builder documents for current organization",
)
def list_documents(
    db: DBSession,
    org: CurrentOrg,
    _ws: OptionalRequireViewer,
    skip: int = 0,
    limit: int = 50,
) -> list[ModelBuilderDocument]:
    """Return all active builder documents for the current organization, newest first."""
    docs = (
        db.query(ModelBuilderDocument)
        .filter(
            ModelBuilderDocument.organization_id == org.id,
            ModelBuilderDocument.is_active.is_(True),
        )
        .order_by(desc(ModelBuilderDocument.updated_at))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return docs


@router.get(
    "/{document_id}",
    response_model=BuilderDocumentResponse,
    summary="Get a single builder document",
)
def get_document(
    document_id: str,
    db: DBSession,
    org: CurrentOrg,
    _ws: OptionalRequireViewer,
) -> ModelBuilderDocument:
    """Return a builder document by ID (must belong to current organization)."""
    return _get_doc_or_404(db, document_id, org.id)


@router.put(
    "/{document_id}",
    response_model=BuilderDocumentResponse,
    summary="Update a builder document",
)
def update_document(
    document_id: str,
    body: BuilderDocumentUpdate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> ModelBuilderDocument:
    """Partially update a builder document.  Only supplied fields are applied."""
    doc = _get_doc_or_404(db, document_id, org.id)

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(doc, field, value)

    doc.updated_at = utcnow()
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_EDIT,
        target_type="builder_document",
        target_id=doc.id,
        target_name=doc.name,
    )
    db.commit()
    db.refresh(doc)
    return doc


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a builder document",
)
def delete_document(
    document_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor,
) -> None:
    """Soft-delete a builder document by setting is_active=False."""
    doc = _get_doc_or_404(db, document_id, org.id)
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MODEL_DELETE,
        target_type="builder_document",
        target_id=doc.id,
        target_name=doc.name,
    )
    doc.is_active = False
    doc.updated_at = utcnow()
    db.commit()


from app.api.v2 import versions as versions_module  # noqa: E402

router.include_router(
    versions_module.router,  # type: ignore[has-type]
    prefix="/{document_id}/versions",
    tags=["versions"],
)
