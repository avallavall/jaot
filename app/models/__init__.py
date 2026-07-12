"""Database models package."""

from app.models.analytics_event import AnalyticsEvent
from app.models.api_key import APIKey
from app.models.audit_log import AuditAction, AuditLog
from app.models.builder_document import ModelBuilderDocument
from app.models.contact_message import ContactMessage
from app.models.conversation_attachment import ConversationAttachment
from app.models.favorite import RecentModel, UserFavorite
from app.models.formulation_rating import FormulationRating
from app.models.llm_conversation import LLMConversation, LLMMessage
from app.models.model_project import (
    ModelProject,
    ModelProjectDataset,
    ModelProjectListing,
    ModelProjectVersion,
)
from app.models.model_version import ModelVersion
from app.models.model_view_event import ModelViewEvent
from app.models.notification import Notification, NotificationChannel, NotificationType
from app.models.notification_preference import NotificationPreference
from app.models.optimization_model import (
    ExecutionStatus,
    ModelCatalog,
    ModelCategory,
    ModelExecution,
    ModelReview,
    ModelStatus,
    OrganizationModel,
)
from app.models.organization import Organization, Plan
from app.models.platform_setting import PlatformSetting
from app.models.platform_setting_audit import PlatformSettingAudit
from app.models.refresh_token import RefreshToken
from app.models.trigger import SolveTrigger, TriggerRun, TriggerSchedule
from app.models.user import User
from app.models.verification_request import VerificationRequest, VerificationStatus
from app.models.workspace import (
    InviteMethod,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceRole,
)

__all__ = [
    # Core
    "Organization",
    "Plan",
    "User",
    "APIKey",
    # Optimization Models
    "ModelCatalog",
    "OrganizationModel",
    "ModelExecution",
    "ModelReview",
    "ModelCategory",
    "ModelStatus",
    "ExecutionStatus",
    # Favorites & Recents
    "UserFavorite",
    "RecentModel",
    # Notifications
    "Notification",
    "NotificationType",
    "NotificationChannel",
    # Builder
    "ModelBuilderDocument",
    "ModelVersion",
    # Model Projects (first-class model entity + commit-grade versions)
    "ModelProject",
    "ModelProjectDataset",
    "ModelProjectListing",
    "ModelProjectVersion",
    # Triggers
    "SolveTrigger",
    "TriggerRun",
    "TriggerSchedule",
    # Workspaces & Collaboration
    "Workspace",
    "WorkspaceMember",
    "WorkspaceInvite",
    "WorkspaceRole",
    "InviteMethod",
    # LLM Conversations
    "LLMConversation",
    "LLMMessage",
    # Feedback
    "FormulationRating",
    # Audit Log
    "AuditLog",
    "AuditAction",
    # Auth
    "RefreshToken",
    # Document Attachments
    "ConversationAttachment",
    # Platform Settings
    "PlatformSetting",
    "PlatformSettingAudit",
    # Seller Experience
    "ModelViewEvent",
    "VerificationRequest",
    "VerificationStatus",
    "NotificationPreference",
    # Feature Usage Analytics
    "AnalyticsEvent",
    # Contact Form
    "ContactMessage",
]
