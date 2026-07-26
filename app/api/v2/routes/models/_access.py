"""Org-scoped lookups shared by the execution routes.

Every org-scoped query must filter by ``organization_id`` — a missing filter is a
cross-tenant leak, not a bug in the usual sense. That filter was being re-typed by
hand at four call sites across the execution and analysis endpoints: correct at all
four, but correct by vigilance rather than by construction (backend audit F-09).

One function, used by every caller, so the filter cannot be forgotten by the next
endpoint added.

(The solver domain has an equivalent helper of its own under
``domains/solver/routes/_helpers.py``. Unifying them means either importing another
package's private module across a layer, or moving ``HTTPException`` into the domain's
service layer — both worse than one small shared function per layer. That unification
belongs to the bounded-context extraction, not here.)
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ModelExecution


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return execution
