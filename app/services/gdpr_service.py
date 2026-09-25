"""GDPR service: data export and account deletion."""

import logging
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, load_only

from app.models import (
    APIKey,
    AuditLog,
    FormulationRating,
    LLMConversation,
    LLMMessage,
    ModelBuilderDocument,
    ModelExecution,
    ModelProject,
    ModelReview,
    Notification,
    Organization,
    RecentModel,
    RefreshToken,
    SolveTrigger,
    TriggerRun,
    User,
    UserFavorite,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
)
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


def export_user_data(db: Session, user: User, org: Organization) -> dict[str, Any]:
    """Export all user-related data as a structured dict (GDPR data portability).

    Returns a dict suitable for JSON serialisation.  API key hashes and
    plaintext keys are intentionally excluded.
    """
    now = utcnow().isoformat()

    # User profile. `name` is the one name the person has: "Display Name" on
    # My Profile edits it (20260925_one_user_name).
    user_data = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "created_at": str(user.created_at) if user.created_at else None,
        "email_verified": user.email_verified,
        "skill_level": user.skill_level,
        "tos_accepted_at": str(user.tos_accepted_at) if user.tos_accepted_at else None,
        "locale": user.locale,
        "slug": user.slug,
        "bio": user.bio,
        "avatar_url": user.avatar_url,
        "linkedin_url": user.linkedin_url,
        "twitter_url": user.twitter_url,
        "is_public_profile": user.is_public_profile,
    }

    # Organization
    org_data = {
        "id": org.id,
        "name": org.name,
    }

    # Model projects (the single model entity post-fusion; legacy org-model rows
    # were backfilled into projects with the same id, so this covers them too).
    #
    # Only the five fields written below are read. The default entity load also
    # pulled `draft_model_json` and `draft_canvas_json` — the whole working copy
    # of every model — to emit an id, a name, a status and a date.
    projects = (
        db.query(ModelProject)
        .options(
            load_only(
                ModelProject.name,
                ModelProject.status,
                ModelProject.source_type,
                ModelProject.created_at,
            )
        )
        .filter_by(organization_id=org.id)
        .all()
    )
    models_data = [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "source_type": p.source_type,
            "created_at": str(p.created_at),
        }
        for p in projects
    ]

    # Executions.
    #
    # Same reason, and this is where it hurt: the default load pulled every
    # run's `input_data` and `result_data` — the compiled problem and the whole
    # solution — for four scalars. Measured on the development database against
    # an organization with 1,253 runs: 128 MB read into memory to write 252 KB
    # of ids and dates, and the request took 19.5 seconds. There is no upper
    # bound on rows here, and there must not be: a data export is all of it.
    executions = (
        db.query(ModelExecution)
        .options(
            load_only(
                ModelExecution.model_project_id,
                ModelExecution.organization_model_id,
                ModelExecution.status,
                ModelExecution.created_at,
            )
        )
        .filter_by(organization_id=org.id)
        .all()
    )
    executions_data = [
        {
            "id": e.id,
            "model_project_id": e.model_project_id or e.organization_model_id,
            "status": e.status,
            "created_at": str(e.created_at),
        }
        for e in executions
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
        "api_keys": keys_data,
        "notifications": notifs_data,
        "workspace_memberships": _workspace_memberships(db, user, org),
        "invites_sent": _invites_sent(db, user, org),
        **_audit_entries(db, user, org),
    }


def _workspace_memberships(db: Session, user: User, org: Organization) -> list[dict[str, Any]]:
    """The workspaces the person belongs to, with their role in each."""
    rows = (
        db.query(
            WorkspaceMember.workspace_id,
            Workspace.name,
            WorkspaceMember.role,
            WorkspaceMember.joined_at,
            WorkspaceMember.invited_by,
        )
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.organization_id == org.id,
        )
        .order_by(WorkspaceMember.joined_at)
        .all()
    )
    return [
        {
            "workspace_id": r.workspace_id,
            "workspace_name": r.name,
            "role": r.role,
            "joined_at": str(r.joined_at),
            "invited_by": r.invited_by,
        }
        for r in rows
    ]


def _invites_sent(db: Session, user: User, org: Organization) -> list[dict[str, Any]]:
    """The invites the person created. The token hash is never exported."""
    rows = (
        db.query(
            WorkspaceInvite.id,
            WorkspaceInvite.workspace_id,
            WorkspaceInvite.method,
            WorkspaceInvite.role,
            WorkspaceInvite.invitee_email,
            WorkspaceInvite.created_at,
            WorkspaceInvite.expires_at,
            WorkspaceInvite.accepted_at,
            WorkspaceInvite.is_revoked,
        )
        .filter(
            WorkspaceInvite.created_by == user.id,
            WorkspaceInvite.organization_id == org.id,
        )
        .order_by(WorkspaceInvite.created_at)
        .all()
    )
    return [
        {
            "id": r.id,
            "workspace_id": r.workspace_id,
            "method": r.method,
            "role": r.role,
            "invitee_email": r.invitee_email,
            "created_at": str(r.created_at),
            "expires_at": str(r.expires_at),
            "accepted_at": str(r.accepted_at) if r.accepted_at else None,
            "is_revoked": r.is_revoked,
        }
        for r in rows
    ]


#: Newest audit entries exported. Every solve writes one, so a busy account
#: holds tens of thousands within the one-year retention. The export says when
#: it stopped at the cap.
AUDIT_EXPORT_LIMIT = 5000


def _audit_entries(db: Session, user: User, org: Organization) -> dict[str, Any]:
    """Audit entries the person made, or that are about them.

    Only the scalar columns are read. ``before_state``, ``after_state`` and the
    metadata can hold a whole model snapshot for an edit, and the export does not
    write them.
    """
    rows = (
        db.query(
            AuditLog.id,
            AuditLog.workspace_id,
            AuditLog.action,
            AuditLog.actor_id,
            AuditLog.actor_name,
            AuditLog.target_type,
            AuditLog.target_id,
            AuditLog.target_name,
            AuditLog.created_at,
        )
        .filter(
            AuditLog.organization_id == org.id,
            or_(
                AuditLog.actor_id == user.id,
                and_(AuditLog.target_type == "user", AuditLog.target_id == user.id),
            ),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(AUDIT_EXPORT_LIMIT + 1)
        .all()
    )
    return {
        "audit_log": [
            {
                "id": r.id,
                "workspace_id": r.workspace_id,
                "action": r.action,
                "actor_id": r.actor_id,
                "actor_name": r.actor_name,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "target_name": r.target_name,
                "created_at": str(r.created_at),
            }
            for r in rows[:AUDIT_EXPORT_LIMIT]
        ],
        "audit_log_truncated": len(rows) > AUDIT_EXPORT_LIMIT,
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
        # The platform-key spend stays in the monthly budget, with no link to
        # the person: an amount, a date and a reason.
        from app.services.llm.cost_tracking import retain_spend_of  # noqa: PLC0415

        retain_spend_of(db, conv_ids, "account_deleted")
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

    # Auth tokens
    db.query(RefreshToken).filter_by(user_id=user_id).delete()
    db.query(APIKey).filter_by(user_id=user_id).delete()

    # ---- If sole member, delete org-scoped records + org ----
    if sole_member:
        # Executions and model projects (DB-level CASCADE removes their versions,
        # datasets, listings, reviews, favorites and recents).
        db.query(ModelExecution).filter_by(organization_id=org_id).delete()
        db.query(ModelProject).filter_by(organization_id=org_id).delete(synchronize_session=False)

        # Workspaces. The money-era tables (ADR-008) that held rows of the
        # organization were dropped by 20260924_drop_billing_tables.
        workspace_ids = [
            w.id for w in db.query(Workspace.id).filter_by(organization_id=org_id).all()
        ]
        if workspace_ids:
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
