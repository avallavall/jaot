"""Database models package."""

from app.models.analytics_event import AnalyticsEvent
from app.models.api_key import APIKey
from app.models.audit_log import AuditAction, AuditLog
from app.models.builder_document import ModelBuilderDocument
from app.models.contact_message import ContactMessage
from app.models.conversation_attachment import ConversationAttachment
from app.models.credit_transaction import CreditTransaction, TransactionType
from app.models.exchange_rate import CREDITS_PER_EUR, ExchangeRate
from app.models.favorite import RecentModel, UserFavorite
from app.models.featured_placement import FeaturedPlacement, PlacementStatus, PlacementType
from app.models.formulation_rating import FormulationRating
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.llm_conversation import LLMConversation, LLMMessage
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
from app.models.organization import Currency, Organization, Plan
from app.models.platform_setting import PlatformSetting
from app.models.platform_setting_audit import PlatformSettingAudit
from app.models.refresh_token import RefreshToken
from app.models.seller_tos_acceptance import SellerToSAcceptance
from app.models.trigger import SolveTrigger, TriggerRun, TriggerSchedule
from app.models.usage_record import UsageRecord
from app.models.user import User
from app.models.verification_request import VerificationRequest, VerificationStatus
from app.models.withdrawal import (
    ScheduleAmountType,
    ScheduleFrequency,
    Withdrawal,
    WithdrawalSchedule,
    WithdrawalStatus,
    WithdrawalType,
)
from app.models.workspace import (
    InviteMethod,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceRole,
)
from app.models.workspace_credits import WorkspaceCreditPool

__all__ = [
    # Core
    "Organization",
    "Plan",
    "Currency",
    "User",
    "APIKey",
    "UsageRecord",
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
    # Credits & Transactions
    "CreditTransaction",
    "TransactionType",
    "ExchangeRate",
    "CREDITS_PER_EUR",
    # Withdrawals
    "Withdrawal",
    "WithdrawalSchedule",
    "WithdrawalStatus",
    "WithdrawalType",
    "ScheduleFrequency",
    "ScheduleAmountType",
    # Notifications
    "Notification",
    "NotificationType",
    "NotificationChannel",
    # Invoices
    "Invoice",
    "InvoiceStatus",
    "InvoiceType",
    # Builder
    "ModelBuilderDocument",
    "ModelVersion",
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
    # Workspace Credits
    "WorkspaceCreditPool",
    # Auth
    "RefreshToken",
    # Document Attachments
    "ConversationAttachment",
    # Platform Settings
    "PlatformSetting",
    "PlatformSettingAudit",
    # Seller Experience
    "ModelViewEvent",
    "FeaturedPlacement",
    "PlacementType",
    "PlacementStatus",
    "VerificationRequest",
    "VerificationStatus",
    "NotificationPreference",
    # Feature Usage Analytics
    "AnalyticsEvent",
    # Seller ToS
    "SellerToSAcceptance",
    # Contact Form
    "ContactMessage",
]
