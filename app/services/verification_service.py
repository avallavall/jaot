"""Verification service for seller badge verification workflow.

Handles request submission, admin review queue, approve/reject with
audit logging, and org is_verified flag management.
"""

import logging

from fastapi import HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction
from app.models.optimization_model import ModelCatalog
from app.models.organization import Organization
from app.models.verification_request import VerificationRequest, VerificationStatus
from app.schemas.verification import AdminVerificationEntry
from app.services.audit_service import log_action
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)


class VerificationService:
    """Service for managing seller verification badge requests."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def request_verification(self, org_id: str, user_id: str) -> VerificationRequest:
        """Submit a verification request for the organization.

        Raises HTTPException 409 if there is already a pending or approved request.
        """
        existing = (
            self.db.query(VerificationRequest)
            .filter(
                VerificationRequest.organization_id == org_id,
                VerificationRequest.status.in_(
                    [
                        VerificationStatus.PENDING.value,
                        VerificationStatus.APPROVED.value,
                    ]
                ),
            )
            .first()
        )
        if existing:
            if existing.status == VerificationStatus.APPROVED.value:
                raise HTTPException(
                    status_code=409,
                    detail="Organization is already verified",
                )
            raise HTTPException(
                status_code=409,
                detail="A verification request is already pending",
            )

        request = VerificationRequest(
            id=generate_id("vrf_"),
            organization_id=org_id,
            requested_by=user_id,
            status=VerificationStatus.PENDING.value,
            created_at=utcnow(),
        )
        self.db.add(request)
        self.db.flush()

        logger.info(
            "Verification request %s created for org %s by user %s",
            request.id,
            org_id,
            user_id,
        )
        return request

    def get_pending_requests(self) -> list[AdminVerificationEntry]:
        """Get all pending verification requests with org details for admin review."""
        requests = (
            self.db.query(VerificationRequest)
            .filter(VerificationRequest.status == VerificationStatus.PENDING.value)
            .order_by(VerificationRequest.created_at.asc())
            .all()
        )

        if not requests:
            return []

        org_ids = [r.organization_id for r in requests]

        # Org details
        orgs = self.db.query(Organization).filter(Organization.id.in_(org_ids)).all()
        org_map = {o.id: o for o in orgs}

        # Published model counts
        model_counts = (
            self.db.query(
                ModelCatalog.author_organization_id,
                func.count().label("cnt"),
            )
            .filter(
                ModelCatalog.author_organization_id.in_(org_ids),
                ModelCatalog.status == "published",
            )
            .group_by(ModelCatalog.author_organization_id)
            .all()
        )
        models_map = {r.author_organization_id: r.cnt for r in model_counts}

        result = []
        for req in requests:
            org = org_map.get(req.organization_id)
            if not org:
                continue

            profile_fields = [
                org.bio,
                org.logo_url,
                org.website_url,
                org.linkedin_url,
                org.twitter_url,
            ]
            filled = sum(1 for f in profile_fields if f)
            completeness = filled / len(profile_fields)

            result.append(
                AdminVerificationEntry(
                    id=req.id,
                    organization_id=req.organization_id,
                    org_name=org.name,
                    profile_completeness=round(completeness, 2),
                    models_published=models_map.get(req.organization_id, 0),
                    member_since=org.created_at.strftime("%Y-%m-%d")
                    if org.created_at
                    else "unknown",
                    status=req.status,
                    created_at=req.created_at,
                )
            )

        return result

    def approve(
        self,
        request_id: str,
        admin_user_id: str,
        note: str | None = None,
        admin_user: object | None = None,
    ) -> VerificationRequest:
        """Approve a verification request. Sets Organization.is_verified=True."""
        req = (
            self.db.query(VerificationRequest).filter(VerificationRequest.id == request_id).first()
        )
        if not req:
            raise HTTPException(status_code=404, detail="Verification request not found")
        if req.status != VerificationStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Only pending requests can be approved")

        now = utcnow()
        req.status = VerificationStatus.APPROVED.value
        req.reviewed_by = admin_user_id
        req.reviewed_at = now
        req.admin_note = note

        org = self.db.query(Organization).filter(Organization.id == req.organization_id).first()
        if org:
            org.is_verified = True

        # Audit log
        log_action(
            db=self.db,
            organization_id=req.organization_id,
            actor=admin_user,  # type: ignore[arg-type]
            action=AuditAction.VERIFICATION_APPROVE,
            target_type="verification_request",
            target_id=req.id,
            target_name=org.name if org else None,
            metadata={"admin_note": note},
            actor_id_override=admin_user_id if admin_user is None else None,
            actor_name_override="admin" if admin_user is None else None,
        )

        logger.info(
            "Verification request %s approved by %s for org %s",
            request_id,
            admin_user_id,
            req.organization_id,
        )
        return req

    def reject(
        self,
        request_id: str,
        admin_user_id: str,
        note: str | None = None,
        admin_user: object | None = None,
    ) -> VerificationRequest:
        """Reject a verification request."""
        req = (
            self.db.query(VerificationRequest).filter(VerificationRequest.id == request_id).first()
        )
        if not req:
            raise HTTPException(status_code=404, detail="Verification request not found")
        if req.status != VerificationStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Only pending requests can be rejected")

        now = utcnow()
        req.status = VerificationStatus.REJECTED.value
        req.reviewed_by = admin_user_id
        req.reviewed_at = now
        req.admin_note = note

        # Audit log
        log_action(
            db=self.db,
            organization_id=req.organization_id,
            actor=admin_user,  # type: ignore[arg-type]
            action=AuditAction.VERIFICATION_REJECT,
            target_type="verification_request",
            target_id=req.id,
            metadata={"admin_note": note},
            actor_id_override=admin_user_id if admin_user is None else None,
            actor_name_override="admin" if admin_user is None else None,
        )

        logger.info(
            "Verification request %s rejected by %s for org %s",
            request_id,
            admin_user_id,
            req.organization_id,
        )
        return req

    def get_request_for_org(self, org_id: str) -> VerificationRequest | None:
        """Get the latest verification request for an organization."""
        return (
            self.db.query(VerificationRequest)
            .filter(VerificationRequest.organization_id == org_id)
            .order_by(desc(VerificationRequest.created_at))
            .first()
        )
