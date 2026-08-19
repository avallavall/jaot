"""Org-scoped lookups shared across the v2 API layer.

Every org-scoped query must filter by ``organization_id`` — a missing filter is a
cross-tenant leak, not a bug in the usual sense. That filter was being re-typed by
hand at four call sites across the execution and analysis endpoints: correct at all
four, but correct by vigilance rather than by construction (backend audit F-09).

One function, used by every caller, so the filter cannot be forgotten by the next
endpoint added.

It lived under ``routes/models/`` while those were its only callers. The explainer
and solve endpoints were re-typing the same lookup from a different package, so it
moved up to the layer they share rather than being imported across packages by its
private name (D-19).

(The solver domain has an equivalent helper of its own under
``domains/solver/routes/_helpers.py``. Unifying them means either importing another
package's private module across a layer, or moving ``HTTPException`` into the domain's
service layer — both worse than one small shared function per layer. That unification
belongs to the bounded-context extraction, not here.)
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ModelBuilderDocument, ModelExecution
from app.shared.core.http_errors import CodedHTTPException


def execution_or_404(db: Session, execution_id: str, org_id: str) -> ModelExecution:
    """Load an execution owned by ``org_id``, or raise 404.

    404 (not 403) on a foreign execution on purpose: telling a caller that an id
    exists but belongs to someone else is itself a leak.
    """
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.id == execution_id,
            ModelExecution.organization_id == org_id,
        )
        .first()
    )
    if not execution:
        # `detail` stays English — it is the API contract, and what a non-browser
        # client reads. The code is what a page in another language renders:
        # "Execution not found" was sitting in English inside a Spanish page.
        raise CodedHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found",
            code="execution.not_found",
        )
    return execution


def builder_document_or_404(db: Session, document_id: str, org_id: str) -> ModelBuilderDocument:
    """Load an active builder document owned by ``org_id``, or raise 404.

    Same story as :func:`execution_or_404`: it lived as a private helper in
    ``builder.py``, which ``versions.py`` was already importing by its private
    name while ``projects.py`` and ``triggers.py`` re-typed the three filters
    instead (``is_active`` among them — the one easiest to forget, and the one
    that would resurrect a deleted document).
    """
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Builder document not found"
        )
    return doc
