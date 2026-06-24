"""GDPR service: data export and account deletion."""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    APIKey,
    AuditLog,
    CreditTransaction,
    FormulationRating,
    LLMConversation,
    LLMMessage,
    ModelBuilderDocument,
    ModelExecution,
    ModelReview,
    Notification,
    Organization,
    OrganizationModel,
    RecentModel,
    RefreshToken,
    SolveTrigger,
    TriggerRun,
    UsageRecord,
    User,
    UserFavorite,
    Withdrawal,
    WithdrawalSchedule,
    Workspace,
    WorkspaceCreditPool,
    WorkspaceInvite,
    WorkspaceMember,
)
from app.models.invoice import Invoice
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


def export_user_data(db: Session, user: User, org: Organization) -> dict[str, Any]:
    """Export all user-related data as a structured dict (GDPR data portability).

    Returns a dict suitable for JSON serialisation.  API key hashes and
    plaintext keys are intentionally excluded.
    """
    now = utcnow().isoformat()

    # User profile
    user_data = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "created_at": str(user.created_at) if user.created_at else None,
        "email_verified": user.email_verified,
        "skill_level": user.skill_level,
        "tos_accepted_at": str(user.tos_accepted_at) if user.tos_accepted_at else None,
    }

    # Organization
    org_data = {
        "id": org.id,
        "name": org.name,
        "plan": org.plan,
        "credits_balance": org.credits_balance,
    }

    # Organization models
    org_models = db.query(OrganizationModel).filter_by(organization_id=org.id).all()
    models_data = [
        {
            "id": m.id,
            "catalog_id": m.catalog_id,
            "is_active": m.is_active,
            "created_at": str(m.created_at),
        }
        for m in org_models
    ]

    # Executions
    executions = db.query(ModelExecution).filter_by(organization_id=org.id).all()
    executions_data = [
        {
            "id": e.id,
            "organization_model_id": e.organization_model_id,
            "status": e.status,
            "created_at": str(e.created_at),
            "credits_consumed": e.credits_consumed,
        }
        for e in executions
    ]

    # Credit transactions
    txns = db.query(CreditTransaction).filter_by(organization_id=org.id).all()
    txns_data = [
        {
            "id": t.id,
            "credits_amount": t.credits_amount,
            "balance_after": t.balance_after,
            "description": t.description,
            "transaction_type": t.transaction_type,
            "created_at": str(t.created_at),
        }
        for t in txns
    ]

    # API keys -- id + name + created_at only, NO hashes
    api_keys = db.query(APIKey).filter_by(user_id=user.id).all()
    keys_data = [{"id": k.id, "name": k.name, "created_at": str(k.created_at)} for k in api_keys]

    # Notifications
    notifs = db.query(Notification).filter_by(user_id=user.id).all()
    notifs_data = [
        {
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "type": n.type,
            "created_at": str(n.created_at),
        }
        for n in notifs
    ]

    return {
        "exported_at": now,
        "user": user_data,
        "organization": org_data,
        "models": models_data,
        "executions": executions_data,
        "credit_transactions": txns_data,
        "api_keys": keys_data,
        "notifications": notifs_data,
    }


def delete_user_account(db: Session, user: User) -> None:
    """Delete a user and all their related data (GDPR right to erasure).

    Uses caller-commits pattern -- the caller must call ``db.commit()``.

    If the user is the sole member of their organization, the org and its
    data are also deleted.
    """
    user_id = user.id
    org_id = user.organization_id

    member_count = (
        db.query(User)
        .filter(
            User.organization_id == org_id,
            User.id != user_id,
        )
        .count()
    )
    sole_member = member_count == 0

    # ---- Delete user-scoped records (FK-safe order, children first) ----

    # Formulation ratings
    db.query(FormulationRating).filter_by(user_id=user_id).delete()

    # LLM messages via conversations
    conv_ids = [c.id for c in db.query(LLMConversation.id).filter_by(user_id=user_id).all()]
    if conv_ids:
        db.query(LLMMessage).filter(LLMMessage.conversation_id.in_(conv_ids)).delete(
            synchronize_session=False
        )
    db.query(LLMConversation).filter_by(user_id=user_id).delete()

    # Triggers -- runs first, then triggers
    trigger_ids = [t.id for t in db.query(SolveTrigger.id).filter_by(created_by=user_id).all()]
    if trigger_ids:
        db.query(TriggerRun).filter(TriggerRun.trigger_id.in_(trigger_ids)).delete(
            synchronize_session=False
        )
    db.query(SolveTrigger).filter_by(created_by=user_id).delete()

    # Workspace records
    db.query(WorkspaceMember).filter_by(user_id=user_id).delete()

    # Builder documents
    db.query(ModelBuilderDocument).filter_by(created_by=user_id).delete()

    # Reviews
    db.query(ModelReview).filter_by(user_id=user_id).delete()

    # Audit logs
    db.query(AuditLog).filter_by(actor_id=user_id).delete()

    # Notifications
    db.query(Notification).filter_by(user_id=user_id).delete()

    # Favorites, recents
    db.query(UserFavorite).filter_by(user_id=user_id).delete()
    db.query(RecentModel).filter_by(user_id=user_id).delete()

    # Usage records
    db.query(UsageRecord).filter_by(user_id=user_id).delete()

    # Auth tokens
    db.query(RefreshToken).filter_by(user_id=user_id).delete()
    db.query(APIKey).filter_by(user_id=user_id).delete()

    # ---- If sole member, delete org-scoped records + org ----
    if sole_member:
        # Executions and org models
        db.query(ModelExecution).filter_by(organization_id=org_id).delete()
        db.query(OrganizationModel).filter_by(organization_id=org_id).delete()

        # Financial records
        db.query(Invoice).filter_by(organization_id=org_id).delete()
        db.query(CreditTransaction).filter_by(organization_id=org_id).delete()
        db.query(WithdrawalSchedule).filter_by(organization_id=org_id).delete()
        db.query(Withdrawal).filter_by(organization_id=org_id).delete()

        # Workspace credit pools & workspaces
        workspace_ids = [
            w.id for w in db.query(Workspace.id).filter_by(organization_id=org_id).all()
        ]
        if workspace_ids:
            db.query(WorkspaceCreditPool).filter(
                WorkspaceCreditPool.workspace_id.in_(workspace_ids)
            ).delete(synchronize_session=False)
            db.query(WorkspaceInvite).filter(
                WorkspaceInvite.workspace_id.in_(workspace_ids)
            ).delete(synchronize_session=False)
            db.query(WorkspaceMember).filter(
                WorkspaceMember.workspace_id.in_(workspace_ids)
            ).delete(synchronize_session=False)
        db.query(Workspace).filter_by(organization_id=org_id).delete()

        # Notifications scoped to org (already deleted user-level ones)
        db.query(Notification).filter_by(organization_id=org_id).delete()

    db.query(User).filter_by(id=user_id).delete()
    db.flush()

    # Delete organization if sole member (after user FK is gone)
    if sole_member:
        db.query(Organization).filter_by(id=org_id).delete()
        db.flush()
    logger.info("Deleted user %s (sole_member=%s, org=%s)", user_id, sole_member, org_id)
