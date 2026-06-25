"""Declarative settings registry for admin configuration panel.

Maps every configurable setting to its type, constraints, category, and label.
This registry is the single source of truth for what settings exist and how they
should be validated. Adding a new runtime setting requires only adding a registry
entry here -- the frontend renders forms dynamically from the registry API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SettingType(str, Enum):
    """Value types for settings."""

    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "str"
    JSON = "json"


class SettingCategory(str, Enum):
    """Categories for organizing settings in the admin UI."""

    SYSTEM = "system"
    APP = "app"
    SERVER = "server"
    BILLING = "billing"
    SOLVER = "solver"
    LLM = "llm"
    EMAIL = "email"
    SECURITY = "security"
    IDENTIFIERS = "identifiers"
    CELERY = "celery"
    METRICS = "metrics"
    MARKETPLACE = "marketplace"
    SECRETS = "secrets"
    RAG = "rag"


@dataclass
class SettingDefinition:
    """Metadata for a single configurable setting."""

    key: str
    label: str
    description: str
    category: SettingCategory
    setting_type: SettingType
    default_value: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None
    is_secret: bool = False
    is_readonly: bool = False


SETTINGS_REGISTRY: list[SettingDefinition] = []

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="MAINTENANCE_MODE",
            label="Maintenance Mode",
            description=(
                "When enabled, non-admin users see a maintenance page. "
                "Admin users can still access everything."
            ),
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.BOOL,
            default_value="false",
            is_secret=False,
            is_readonly=False,
        ),
        SettingDefinition(
            key="SOLVE_MAINTENANCE_MODE",
            label="Solve Maintenance Mode",
            description=(
                "When enabled, POST /solve, /solve/async and "
                "/models/{id}/execute return 503 with Retry-After: 600. "
                "Used during drain+rotate maintenance windows. Other "
                "endpoints remain available."
            ),
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.BOOL,
            default_value="false",
            is_secret=False,
            is_readonly=False,
        ),
    ]
)

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="SOLVER_DEFAULT_TIMEOUT",
            label="Default Timeout",
            description="Default solver timeout in seconds",
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="300",
            min_value=1,
            max_value=3600,
            unit="seconds",
        ),
        SettingDefinition(
            key="SOLVER_VIOLATION_TOLERANCE",
            label="Violation Tolerance",
            description="Solver violation tolerance (0.0 to 1.0)",
            category=SettingCategory.SOLVER,
            setting_type=SettingType.FLOAT,
            default_value="0.000001",
            min_value=0.0,
            max_value=1.0,
        ),
        SettingDefinition(
            key="SOLVER_POOL_SIZE",
            label="Pool Size",
            description="Number of solver threads in pool",
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="4",
            min_value=1,
            max_value=32,
        ),
        SettingDefinition(
            key="SOLVER_TIMEOUT_SECONDS",
            label="Timeout Seconds",
            description="Solver timeout in seconds (per execution)",
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="30",
            min_value=1,
            max_value=3600,
            unit="seconds",
        ),
        SettingDefinition(
            key="hexaly_default_time_limit_seconds",
            label="Hexaly Default Time Limit",
            description=(
                "Default time_limit (seconds) passed to Hexaly "
                "model.param.time_limit when the request omits it. "
                "Hexaly is metaheuristic — an explicit stop is required. "
                "Phase 7 / D-12."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="60",
            min_value=1,
            max_value=3600,
            unit="seconds",
        ),
        SettingDefinition(
            key="EXECUTION_REAPER_PENDING_MAX_SECONDS",
            label="Reaper: Max Pending Age",
            description=(
                "Age in seconds after which a ModelExecution stuck in 'pending' "
                "with no active Celery worker is marked failed and its pre-paid "
                "credits refunded by the execution reaper beat task (W1/F-01)."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="1800",
            min_value=60,
            max_value=86400,
            unit="seconds",
        ),
        SettingDefinition(
            key="EXECUTION_REAPER_RUNNING_MAX_SECONDS",
            label="Reaper: Max Running Age",
            description=(
                "Age in seconds after which a ModelExecution still running (DB "
                "status 'running' or an active Celery worker state) is considered "
                "hung, marked failed, and refunded by the execution reaper. "
                "Default is 2x the maximum per-request solver time limit (3600s)."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="7200",
            min_value=300,
            max_value=172800,
            unit="seconds",
        ),
    ]
)

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="LLM_DEFAULT_MODEL",
            label="Default Model",
            description="Default LLM model for standard requests",
            category=SettingCategory.LLM,
            setting_type=SettingType.STRING,
            default_value="claude-sonnet-4-6",
        ),
        SettingDefinition(
            key="LLM_ADVANCED_MODEL",
            label="Advanced Model",
            description="LLM model for advanced/complex requests",
            category=SettingCategory.LLM,
            setting_type=SettingType.STRING,
            default_value="claude-opus-4-6",
        ),
        SettingDefinition(
            key="LLM_MAX_TOKENS",
            label="Max Tokens",
            description="Maximum tokens per LLM request",
            category=SettingCategory.LLM,
            setting_type=SettingType.INT,
            default_value="16384",
            min_value=1,
            max_value=100000,
            unit="tokens",
        ),
        SettingDefinition(
            key="LLM_MAX_RETRIES",
            label="Max Retries",
            description="Maximum retry attempts for LLM calls",
            category=SettingCategory.LLM,
            setting_type=SettingType.INT,
            default_value="2",
            min_value=0,
            max_value=10,
        ),
        SettingDefinition(
            key="LLM_MAX_OUTPUT_TOKENS_LIMIT",
            label="Max Output Tokens Limit",
            description="Hard limit on LLM output tokens",
            category=SettingCategory.LLM,
            setting_type=SettingType.INT,
            default_value="64000",
            min_value=1,
            max_value=200000,
            unit="tokens",
        ),
        SettingDefinition(
            key="LLM_CONVERSATION_TTL_HOURS",
            label="Conversation TTL",
            description="Hours before LLM conversations expire",
            category=SettingCategory.LLM,
            setting_type=SettingType.INT,
            default_value="24",
            min_value=1,
            max_value=168,
            unit="hours",
        ),
        SettingDefinition(
            key="LLM_RATE_LIMIT_PER_MINUTE",
            label="Rate Limit per Minute",
            description="Max LLM requests per minute",
            category=SettingCategory.LLM,
            setting_type=SettingType.INT,
            default_value="10",
            min_value=1,
            max_value=1000,
        ),
        SettingDefinition(
            key="LLM_RATE_LIMIT_PER_DAY",
            label="Rate Limit per Day",
            description="Max LLM requests per day",
            category=SettingCategory.LLM,
            setting_type=SettingType.INT,
            default_value="100",
            min_value=1,
            max_value=100000,
        ),
        SettingDefinition(
            key="LLM_CREDIT_COST_PER_MESSAGE",
            label="Credit Cost per Message",
            description="Credits charged per LLM message",
            category=SettingCategory.LLM,
            setting_type=SettingType.INT,
            default_value="2",
            min_value=0,
            max_value=100,
            unit="credits",
        ),
        SettingDefinition(
            key="LLM_MONTHLY_BUDGET_EUR",
            label="Monthly Anthropic Budget",
            description=(
                "Real-cost ceiling (EUR) for the AI assistant per calendar "
                "month, measured as SUM(llm_messages.cost_eur). When reached, "
                "the assistant auto-pauses with a friendly notice until the "
                "new month or a budget increase. Prometheus alerts fire at "
                ">80% (warning) and >=100% (critical). Set 0 to disable the "
                "guardrail. W17."
            ),
            category=SettingCategory.LLM,
            setting_type=SettingType.FLOAT,
            default_value="20.0",
            min_value=0,
            max_value=100000,
            unit="EUR",
        ),
        SettingDefinition(
            key="LLM_MODEL_PRICING_EUR_PER_MTOK",
            label="Model Pricing (EUR per MTok)",
            description=(
                'JSON map of Anthropic model id -> {"input": eur, "output": '
                "eur} per million tokens, used to compute llm_messages.cost_eur "
                "from the real token usage returned by the API (W17). The "
                '"default" entry prices unknown/future models and is kept at '
                "Opus rates so surprises over-estimate cost rather than "
                "under-estimate it. Defaults are Anthropic USD list prices "
                "converted at ~1.08 USD/EUR."
            ),
            category=SettingCategory.LLM,
            setting_type=SettingType.JSON,
            default_value=(
                '{"claude-sonnet-4-6": {"input": 2.78, "output": 13.89}, '
                '"claude-opus-4-6": {"input": 4.63, "output": 23.15}, '
                '"claude-opus-4-7": {"input": 4.63, "output": 23.15}, '
                '"claude-opus-4-8": {"input": 4.63, "output": 23.15}, '
                '"claude-haiku-4-5": {"input": 0.93, "output": 4.63}, '
                '"default": {"input": 4.63, "output": 23.15}}'
            ),
        ),
    ]
)

# EMAIL category (8 entries — incl. CONTACT_RECIPIENT, D-07)
SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="EMAIL_BACKEND",
            label="Email Backend",
            description="Email delivery backend (console or smtp)",
            category=SettingCategory.EMAIL,
            setting_type=SettingType.STRING,
            default_value="console",
        ),
        SettingDefinition(
            key="SMTP_HOST",
            label="SMTP Host",
            description="SMTP server hostname",
            category=SettingCategory.EMAIL,
            setting_type=SettingType.STRING,
            default_value="smtp.resend.com",
        ),
        SettingDefinition(
            key="SMTP_PORT",
            label="SMTP Port",
            description="SMTP server port",
            category=SettingCategory.EMAIL,
            setting_type=SettingType.INT,
            default_value="587",
            min_value=1,
            max_value=65535,
        ),
        SettingDefinition(
            key="SMTP_USER",
            label="SMTP User",
            description="SMTP authentication username",
            category=SettingCategory.EMAIL,
            setting_type=SettingType.STRING,
            default_value="resend",
        ),
        SettingDefinition(
            key="SMTP_USE_TLS",
            label="SMTP Use TLS",
            description="Enable TLS for SMTP connections",
            category=SettingCategory.EMAIL,
            setting_type=SettingType.BOOL,
            default_value="true",
        ),
        SettingDefinition(
            key="SMTP_TIMEOUT",
            label="SMTP Timeout",
            description="SMTP connection timeout",
            category=SettingCategory.EMAIL,
            setting_type=SettingType.INT,
            default_value="10",
            min_value=1,
            max_value=60,
            unit="seconds",
        ),
        SettingDefinition(
            key="EMAIL_FROM",
            label="From Address",
            description="Default sender email address",
            category=SettingCategory.EMAIL,
            setting_type=SettingType.STRING,
            default_value="JAOT <noreply@jaot.io>",
        ),
        SettingDefinition(
            key="CONTACT_RECIPIENT",
            label="Contact Form Recipient",
            description=(
                "Email address that receives messages submitted via the public "
                "/contact form. Single recipient (not CSV). Runtime-editable. "
                "This is the public-form inbox; change in admin if you want a "
                "separate triage mailbox. Phase 9 / D-07."
            ),
            category=SettingCategory.EMAIL,
            setting_type=SettingType.STRING,
            default_value="info@jaot.io",
            is_secret=False,
            is_readonly=False,
        ),
    ]
)

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="REGISTRATION_ENABLED",
            label="Public Registration",
            description="Allow new users to register. Disable for soft launch.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.BOOL,
            default_value="false",
            is_secret=False,
            is_readonly=False,
        ),
        SettingDefinition(
            key="JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            label="JWT Access Token Expiry",
            description="Access token expiration time",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="30",
            min_value=1,
            max_value=1440,
            unit="minutes",
        ),
        SettingDefinition(
            key="JWT_REFRESH_TOKEN_EXPIRE_DAYS",
            label="JWT Refresh Token Expiry",
            description="Refresh token expiration time",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="7",
            min_value=1,
            max_value=365,
            unit="days",
        ),
        SettingDefinition(
            key="JWT_REFRESH_TOKEN_REMEMBER_DAYS",
            label="JWT Remember Me Expiry",
            description=("Refresh token expiry when 'remember me' is checked"),
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="30",
            min_value=1,
            max_value=365,
            unit="days",
        ),
        SettingDefinition(
            key="API_KEY_DEFAULT_EXPIRY_DAYS",
            label="API Key Default Expiry",
            description="Default expiration for new API keys",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="365",
            min_value=1,
            max_value=3650,
            unit="days",
        ),
        SettingDefinition(
            key="API_KEY_ACTIVE_BY_DEFAULT",
            label="API Key Active by Default",
            description="Whether new API keys are active immediately",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.BOOL,
            default_value="true",
        ),
        SettingDefinition(
            key="RATE_LIMIT_WINDOW_SECONDS",
            label="Rate Limit Window",
            description="Time window for rate limiting",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="60",
            min_value=1,
            max_value=3600,
            unit="seconds",
        ),
        SettingDefinition(
            key="RATE_LIMIT_DAILY_WINDOW_SECONDS",
            label="Daily Rate Limit Window",
            description="Time window for daily rate limiting",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="86400",
            min_value=1,
            max_value=172800,
            unit="seconds",
        ),
    ]
)

# BILLING category (38 entries: MONETIZATION_ENABLED + DEFAULT_PLAN + 4 tiers x 9 fields)

SETTINGS_REGISTRY.append(
    SettingDefinition(
        key="MONETIZATION_ENABLED",
        label="Monetization Enabled",
        description=(
            "Master switch for every paid feature. When OFF (the default), the "
            "platform is fully free and collaborative: marketplace models are "
            "free to publish and use, no commission is charged, and billing, "
            "payouts, Stripe Connect onboarding, and featured-placement "
            "purchases are disabled (their endpoints respond 404). Turn ON only "
            "on a self-hosted deployment that brings its own Stripe keys to "
            "restore the paid marketplace."
        ),
        category=SettingCategory.BILLING,
        setting_type=SettingType.BOOL,
        default_value="false",
        is_secret=False,
        is_readonly=False,
    ),
)

SETTINGS_REGISTRY.append(
    SettingDefinition(
        key="DEFAULT_PLAN",
        label="Default Plan",
        description="Default subscription plan for new organizations",
        category=SettingCategory.BILLING,
        setting_type=SettingType.STRING,
        default_value="free",
    ),
)

_PLAN_TIERS = ["free", "starter", "pro", "business"]
_PLAN_FIELDS: list[tuple[str, str, SettingType, float | None, float | None, str | None]] = [
    # (field, label, type, min, max, unit)
    ("credits", "Credits", SettingType.INT, 0, 1000000, "credits"),
    ("monthly_quota", "Monthly Quota", SettingType.INT, 0, 1000000, "credits"),
    ("rate_limit_per_minute", "Rate Limit/Min", SettingType.INT, 0, 10000, None),
    ("rate_limit_per_day", "Rate Limit/Day", SettingType.INT, 0, 1000000, None),
    (
        "max_solve_time_seconds",
        "Max Solve Time",
        SettingType.INT,
        1,
        86400,
        "seconds",
    ),
    ("max_variables", "Max Variables", SettingType.INT, 1, 10000000, None),
    ("max_daily_solves", "Max Daily Solves", SettingType.INT, 1, 100000, None),
    ("max_cron_schedules", "Max Cron Schedules", SettingType.INT, 0, 1000, None),
    ("allowed_features", "Allowed Features", SettingType.JSON, None, None, None),
]

_ALLOWED_FEATURES_DEFAULT = (
    '["llm_assistant","warm_start","sensitivity_analysis","cron_scheduling"]'
)

# Default values per tier, keyed by (tier, field)
_PLAN_DEFAULTS: dict[tuple[str, str], str] = {
    # Default plan ("free"): no paid tiers anymore — every signup gets full,
    # business-level access. The platform-wide monthly LLM budget remains the
    # real cost ceiling. Applied to prod runtime 2026-06-24 and mirrored here so
    # fresh installs / DB reseeds match. (starter/pro/business kept as legacy.)
    ("free", "credits"): "20000",
    ("free", "monthly_quota"): "20000",
    ("free", "rate_limit_per_minute"): "120",
    ("free", "rate_limit_per_day"): "50000",
    ("free", "max_solve_time_seconds"): "3600",
    ("free", "max_variables"): "10000000",
    ("free", "max_daily_solves"): "50000",
    ("free", "max_cron_schedules"): "50",
    ("free", "allowed_features"): _ALLOWED_FEATURES_DEFAULT,
    # Starter tier
    ("starter", "credits"): "600",
    ("starter", "monthly_quota"): "600",
    ("starter", "rate_limit_per_minute"): "20",
    ("starter", "rate_limit_per_day"): "500",
    ("starter", "max_solve_time_seconds"): "300",
    ("starter", "max_variables"): "100000",
    ("starter", "max_daily_solves"): "500",
    ("starter", "max_cron_schedules"): "5",
    ("starter", "allowed_features"): _ALLOWED_FEATURES_DEFAULT,
    # Pro tier
    ("pro", "credits"): "2500",
    ("pro", "monthly_quota"): "2500",
    ("pro", "rate_limit_per_minute"): "60",
    ("pro", "rate_limit_per_day"): "5000",
    ("pro", "max_solve_time_seconds"): "900",
    ("pro", "max_variables"): "1000000",
    ("pro", "max_daily_solves"): "5000",
    ("pro", "max_cron_schedules"): "15",
    ("pro", "allowed_features"): _ALLOWED_FEATURES_DEFAULT,
    # Business tier
    ("business", "credits"): "20000",
    ("business", "monthly_quota"): "20000",
    ("business", "rate_limit_per_minute"): "120",
    ("business", "rate_limit_per_day"): "50000",
    ("business", "max_solve_time_seconds"): "3600",
    ("business", "max_variables"): "10000000",
    ("business", "max_daily_solves"): "50000",
    ("business", "max_cron_schedules"): "50",
    ("business", "allowed_features"): _ALLOWED_FEATURES_DEFAULT,
}

for _tier in _PLAN_TIERS:
    for _field, _label, _stype, _min, _max, _unit in _PLAN_FIELDS:
        SETTINGS_REGISTRY.append(
            SettingDefinition(
                key=f"plan_{_tier}_{_field}",
                label=f"{_tier.title()} {_label}",
                description=f"{_label} for {_tier.title()} plan",
                category=SettingCategory.BILLING,
                setting_type=_stype,
                default_value=_PLAN_DEFAULTS.get((_tier, _field)),
                min_value=_min,
                max_value=_max,
                unit=_unit,
            ),
        )


SETTINGS_REGISTRY.append(
    SettingDefinition(
        key="marketplace_commission_rate",
        label="Commission Rate",
        description="Marketplace commission rate (0.0 to 0.50)",
        category=SettingCategory.MARKETPLACE,
        setting_type=SettingType.FLOAT,
        default_value="0.10",
        min_value=0.0,
        max_value=0.50,
        unit="%",
    ),
)

_PLACEMENT_TYPES = [
    "homepage_carousel",
    "category_spotlight",
    "search_boost",
    "promoted_badge",
]
_PLACEMENT_DURATIONS = ["7d", "14d", "30d"]

# Default pricing for featured placements
_PLACEMENT_DEFAULTS: dict[str, str] = {
    "featured_placement_homepage_carousel_7d": "500",
    "featured_placement_homepage_carousel_14d": "900",
    "featured_placement_homepage_carousel_30d": "1200",
    "featured_placement_category_spotlight_7d": "300",
    "featured_placement_category_spotlight_14d": "550",
    "featured_placement_category_spotlight_30d": "750",
    "featured_placement_search_boost_7d": "200",
    "featured_placement_search_boost_14d": "350",
    "featured_placement_search_boost_30d": "500",
    "featured_placement_promoted_badge_7d": "100",
    "featured_placement_promoted_badge_14d": "175",
    "featured_placement_promoted_badge_30d": "250",
}

for _ptype in _PLACEMENT_TYPES:
    for _dur in _PLACEMENT_DURATIONS:
        _key = f"featured_placement_{_ptype}_{_dur}"
        SETTINGS_REGISTRY.append(
            SettingDefinition(
                key=_key,
                label=(f"{_ptype.replace('_', ' ').title()} ({_dur})"),
                description=(f"Pricing for {_ptype.replace('_', ' ')} placement ({_dur})"),
                category=SettingCategory.MARKETPLACE,
                setting_type=SettingType.INT,
                default_value=_PLACEMENT_DEFAULTS.get(_key),
                min_value=0,
                max_value=100000,
                unit="credits",
            ),
        )

# SECRETS category (10 entries — all readonly, masked)

_SECRET_KEYS = [
    ("DATABASE_URL", "Database URL", "PostgreSQL connection string"),
    ("JWT_SECRET", "JWT Secret", "Secret key for JWT signing"),
    ("ANTHROPIC_API_KEY", "Anthropic API Key", "API key for Claude LLM"),
    ("STRIPE_SECRET_KEY", "Stripe Secret Key", "Stripe API secret key"),
    ("STRIPE_WEBHOOK_SECRET", "Stripe Webhook Secret", "Stripe webhook signing secret"),
    ("SMTP_PASSWORD", "SMTP Password", "SMTP authentication password"),
    ("DISCOURSE_SSO_SECRET", "Discourse SSO Secret", "Discourse single sign-on secret"),
    ("STORAGE_ACCESS_KEY", "Storage Access Key", "Object storage access key"),
    ("STORAGE_SECRET_KEY", "Storage Secret Key", "Object storage secret key"),
]

for _key, _label, _desc in _SECRET_KEYS:
    SETTINGS_REGISTRY.append(
        SettingDefinition(
            key=_key,
            label=_label,
            description=_desc,
            category=SettingCategory.SECRETS,
            setting_type=SettingType.STRING,
            default_value="",
            is_secret=True,
            is_readonly=False,
        ),
    )

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="APP_NAME",
            label="Application Name",
            description="Name of the application",
            category=SettingCategory.APP,
            setting_type=SettingType.STRING,
            default_value="JAOT",
        ),
        SettingDefinition(
            key="APP_VERSION",
            label="Application Version",
            description="Current application version",
            category=SettingCategory.APP,
            setting_type=SettingType.STRING,
            default_value="2.0.0",
            is_readonly=True,
        ),
        SettingDefinition(
            key="API_DESCRIPTION",
            label="API Description",
            description="Description shown in API documentation",
            category=SettingCategory.APP,
            setting_type=SettingType.STRING,
            default_value=("Multi-tenant optimization-as-a-service platform"),
        ),
        SettingDefinition(
            key="HOME_ANNOUNCEMENT_ENABLED",
            label="Home announcement enabled",
            description=(
                "Toggle the top-of-page announcement banner on public pages. "
                "When disabled, the banner is not rendered regardless of text."
            ),
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.BOOL,
            default_value="false",
        ),
        *[
            SettingDefinition(
                key=f"HOME_ANNOUNCEMENT_TEXT_{code.upper()}",
                label=f"Announcement text ({name})",
                description=(
                    f"Banner text for {name}. Multiple messages can be separated "
                    f"with '|' for rotation. Leave empty to skip this locale."
                ),
                category=SettingCategory.SYSTEM,
                setting_type=SettingType.STRING,
                default_value="",
            )
            for code, name in [
                ("en", "English"),
                ("es", "Spanish"),
                ("ca", "Catalan"),
                ("fr", "French"),
                ("de", "German"),
            ]
        ],
        SettingDefinition(
            key="HOME_ANNOUNCEMENT_ROTATION_SECONDS",
            label="Announcement rotation interval (seconds)",
            description=(
                "How many seconds each message is shown before rotating to the "
                "next one. Only applies when there are multiple messages."
            ),
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.INT,
            default_value="5",
            min_value=2,
            max_value=60,
            unit="seconds",
        ),
    ]
)

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="HOST",
            label="Host",
            description="Server bind host address",
            category=SettingCategory.SERVER,
            setting_type=SettingType.STRING,
            default_value="0.0.0.0",
        ),
        SettingDefinition(
            key="PORT",
            label="Port",
            description="Server bind port",
            category=SettingCategory.SERVER,
            setting_type=SettingType.INT,
            default_value="8001",
            min_value=1,
            max_value=65535,
        ),
        SettingDefinition(
            key="WORKERS",
            label="Workers",
            description="Number of uvicorn worker processes",
            category=SettingCategory.SERVER,
            setting_type=SettingType.INT,
            default_value="1",
            min_value=1,
            max_value=32,
        ),
        SettingDefinition(
            key="GZIP_MINIMUM_SIZE",
            label="Gzip Minimum Size",
            description=("Minimum response size in bytes to apply gzip"),
            category=SettingCategory.SERVER,
            setting_type=SettingType.INT,
            default_value="1000",
            min_value=0,
            max_value=100000,
            unit="bytes",
        ),
    ]
)

# IDENTIFIERS category — ID prefixes and API key defaults
SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="ID_PREFIX_ORGANIZATION",
            label="Organization ID Prefix",
            description="Prefix for organization IDs",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="org_",
        ),
        SettingDefinition(
            key="ID_PREFIX_USER",
            label="User ID Prefix",
            description="Prefix for user IDs",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="usr_",
        ),
        SettingDefinition(
            key="ID_PREFIX_API_KEY",
            label="API Key ID Prefix",
            description="Prefix for API key IDs",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="key_",
        ),
        SettingDefinition(
            key="ID_PREFIX_USAGE_RECORD",
            label="Usage Record ID Prefix",
            description="Prefix for usage record IDs",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="usage_",
        ),
        SettingDefinition(
            key="ID_PREFIX_RATE_LIMIT_EVENT",
            label="Rate Limit Event ID Prefix",
            description="Prefix for rate limit event IDs",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="rl_",
        ),
        SettingDefinition(
            key="API_KEY_DEFAULT_NAME",
            label="Default API Key Name",
            description="Default name for newly created API keys",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="Default API Key",
        ),
        SettingDefinition(
            key="API_KEY_DEFAULT_PREFIX",
            label="API Key Default Prefix",
            description="Prefix for live API keys",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="ok_live_",
        ),
        SettingDefinition(
            key="API_KEY_TEST_PREFIX",
            label="API Key Test Prefix",
            description="Prefix for test API keys",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="ok_test_",
        ),
        SettingDefinition(
            key="DEFAULT_USER_ROLE",
            label="Default User Role",
            description="Default role assigned to new users",
            category=SettingCategory.IDENTIFIERS,
            setting_type=SettingType.STRING,
            default_value="member",
        ),
    ]
)

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="CELERY_MAX_RETRIES",
            label="Max Retries",
            description="Maximum retry attempts for failed tasks",
            category=SettingCategory.CELERY,
            setting_type=SettingType.INT,
            default_value="3",
            min_value=0,
            max_value=20,
        ),
        SettingDefinition(
            key="CELERY_DEFAULT_RETRY_DELAY",
            label="Default Retry Delay",
            description="Seconds between retry attempts",
            category=SettingCategory.CELERY,
            setting_type=SettingType.INT,
            default_value="300",
            min_value=1,
            max_value=3600,
            unit="seconds",
        ),
        SettingDefinition(
            key="CELERY_RESULT_EXPIRES",
            label="Result Expiry",
            description="Seconds before task results expire",
            category=SettingCategory.CELERY,
            setting_type=SettingType.INT,
            default_value="604800",
            min_value=60,
            max_value=2592000,
            unit="seconds",
        ),
        SettingDefinition(
            key="CRON_DEFAULT_CREDIT_ESTIMATE",
            label="Cron Default Credit Estimate",
            description=("Default credit estimate for cron runs without prior run history"),
            category=SettingCategory.CELERY,
            setting_type=SettingType.INT,
            default_value="1",
            min_value=0,
            max_value=1000,
            unit="credits",
        ),
    ]
)

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="METRICS_MAX_RECENT_REQUESTS",
            label="Max Recent Requests",
            description=("Maximum number of recent requests stored for metrics"),
            category=SettingCategory.METRICS,
            setting_type=SettingType.INT,
            default_value="100",
            min_value=1,
            max_value=10000,
        ),
        SettingDefinition(
            key="METRICS_DEFAULT_RECENT_LIMIT",
            label="Default Recent Limit",
            description="Default limit for recent metrics queries",
            category=SettingCategory.METRICS,
            setting_type=SettingType.INT,
            default_value="10",
            min_value=1,
            max_value=1000,
        ),
    ]
)

# Additional BILLING entries — pricing, holding, thresholds
SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="HOLDING_PERIOD_DAYS",
            label="Holding Period",
            description=("Days before earned credits can be withdrawn"),
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="14",
            min_value=0,
            max_value=365,
            unit="days",
        ),
        SettingDefinition(
            key="LOW_CREDITS_THRESHOLD_PCT",
            label="Low Credits Threshold",
            description=("Percentage threshold for low credits warning"),
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="10",
            min_value=0,
            max_value=100,
            unit="%",
        ),
        SettingDefinition(
            key="plan_free_monthly_price",
            label="Free Monthly Price",
            description="Monthly price for Free plan",
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="0",
            min_value=0,
            max_value=100000,
            unit="USD cents",
        ),
        SettingDefinition(
            key="plan_starter_monthly_price",
            label="Starter Monthly Price",
            description="Monthly price for Starter plan",
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="19",
            min_value=0,
            max_value=100000,
            unit="USD",
        ),
        SettingDefinition(
            key="plan_pro_monthly_price",
            label="Pro Monthly Price",
            description="Monthly price for Pro plan",
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="49",
            min_value=0,
            max_value=100000,
            unit="USD",
        ),
        SettingDefinition(
            key="plan_business_monthly_price",
            label="Business Monthly Price",
            description="Monthly price for Business plan",
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="149",
            min_value=0,
            max_value=100000,
            unit="USD",
        ),
        SettingDefinition(
            key="plan_starter_annual_price",
            label="Starter Annual Price",
            description="Annual price for Starter plan",
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="190",
            min_value=0,
            max_value=1000000,
            unit="USD",
        ),
        SettingDefinition(
            key="plan_pro_annual_price",
            label="Pro Annual Price",
            description="Annual price for Pro plan",
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="490",
            min_value=0,
            max_value=1000000,
            unit="USD",
        ),
        SettingDefinition(
            key="plan_business_annual_price",
            label="Business Annual Price",
            description="Annual price for Business plan",
            category=SettingCategory.BILLING,
            setting_type=SettingType.INT,
            default_value="1490",
            min_value=0,
            max_value=1000000,
            unit="USD",
        ),
        SettingDefinition(
            key="STRIPE_PRICE_STARTER_MONTHLY",
            label="Stripe Starter Monthly Price ID",
            description="Stripe Price ID for Starter monthly",
            category=SettingCategory.BILLING,
            setting_type=SettingType.STRING,
            default_value="",
        ),
        SettingDefinition(
            key="STRIPE_PRICE_PRO_MONTHLY",
            label="Stripe Pro Monthly Price ID",
            description="Stripe Price ID for Pro monthly",
            category=SettingCategory.BILLING,
            setting_type=SettingType.STRING,
            default_value="",
        ),
        SettingDefinition(
            key="STRIPE_PRICE_BUSINESS_MONTHLY",
            label="Stripe Business Monthly Price ID",
            description="Stripe Price ID for Business monthly",
            category=SettingCategory.BILLING,
            setting_type=SettingType.STRING,
            default_value="",
        ),
        SettingDefinition(
            key="STRIPE_PRICE_TOPUP_500",
            label="Stripe Topup 500 Price ID",
            description="Stripe Price ID for 500 credit topup",
            category=SettingCategory.BILLING,
            setting_type=SettingType.STRING,
            default_value="",
        ),
        SettingDefinition(
            key="STRIPE_PRICE_TOPUP_2000",
            label="Stripe Topup 2000 Price ID",
            description="Stripe Price ID for 2000 credit topup",
            category=SettingCategory.BILLING,
            setting_type=SettingType.STRING,
            default_value="",
        ),
        SettingDefinition(
            key="STRIPE_PRICE_TOPUP_5000",
            label="Stripe Topup 5000 Price ID",
            description="Stripe Price ID for 5000 credit topup",
            category=SettingCategory.BILLING,
            setting_type=SettingType.STRING,
            default_value="",
        ),
        SettingDefinition(
            key="STRIPE_PRICE_TOPUP_20000",
            label="Stripe Topup 20000 Price ID",
            description="Stripe Price ID for 20000 credit topup",
            category=SettingCategory.BILLING,
            setting_type=SettingType.STRING,
            default_value="",
        ),
    ]
)

# BILLING — Phase 7.4 / PRC-01 / D-02 / D-03 (3 entries)
#
# Per-solver credit multiplier. Applied in calculate_credits() AFTER the
# auto-router decides the effective solver. Hexaly solves cost 5x more in
# credits than SCIP solves; HiGHS sits in the middle at 1.2x. Runtime-
# configurable via the platform_settings admin panel.
SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="pricing.solver_multiplier.scip",
            label="SCIP credit multiplier",
            description=(
                "Per-solve credit multiplier applied when the effective "
                "solver is SCIP. Default 1.0 — SCIP is the baseline. "
                "Phase 7.4 / PRC-01 / D-02."
            ),
            category=SettingCategory.BILLING,
            setting_type=SettingType.FLOAT,
            default_value="1.0",
            min_value=0.1,
            max_value=100.0,
        ),
        SettingDefinition(
            key="pricing.solver_multiplier.highs",
            label="HiGHS credit multiplier",
            description=(
                "Per-solve credit multiplier applied when the effective "
                "solver is HiGHS. Default 1.2. "
                "Phase 7.4 / PRC-01 / D-02."
            ),
            category=SettingCategory.BILLING,
            setting_type=SettingType.FLOAT,
            default_value="1.2",
            min_value=0.1,
            max_value=100.0,
        ),
        SettingDefinition(
            key="pricing.solver_multiplier.hexaly",
            label="Hexaly credit multiplier",
            description=(
                "Per-solve credit multiplier applied when the effective "
                "solver is Hexaly. Default 5.0 — commercial solver; the "
                "deployment mounts a single instance-level Hexaly .lic (BYOL) "
                "per D-01. Phase 7.4 / PRC-01 / D-02."
            ),
            category=SettingCategory.BILLING,
            setting_type=SettingType.FLOAT,
            default_value="5.0",
            min_value=0.1,
            max_value=100.0,
        ),
    ]
)

# RAG category — retrieval-augmented generation for formulation assistant
SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="RAG_ENABLED",
            label="RAG Enabled",
            description="Enable RAG context injection for the formulation assistant",
            category=SettingCategory.RAG,
            setting_type=SettingType.BOOL,
            default_value="false",
        ),
        SettingDefinition(
            key="RAG_AB_TEST_PERCENTAGE",
            label="A/B Test Percentage",
            description="Percentage of requests using RAG (0-100, for A/B testing)",
            category=SettingCategory.RAG,
            setting_type=SettingType.INT,
            default_value="0",
            min_value=0,
            max_value=100,
            unit="%",
        ),
        SettingDefinition(
            key="RAG_TOP_K",
            label="Top K Results",
            description="Number of documents to retrieve per query",
            category=SettingCategory.RAG,
            setting_type=SettingType.INT,
            default_value="5",
            min_value=1,
            max_value=20,
        ),
        SettingDefinition(
            key="RAG_MIN_SCORE",
            label="Minimum Score",
            description="Minimum cosine similarity score to include a result",
            category=SettingCategory.RAG,
            setting_type=SettingType.FLOAT,
            default_value="0.35",
            min_value=0.0,
            max_value=1.0,
        ),
        SettingDefinition(
            key="RAG_MAX_TOKENS",
            label="Max Context Tokens",
            description="Maximum tokens for RAG context in the system prompt",
            category=SettingCategory.RAG,
            setting_type=SettingType.INT,
            default_value="3000",
            min_value=500,
            max_value=10000,
            unit="tokens",
        ),
    ]
)

SETTINGS_REGISTRY.append(
    SettingDefinition(
        key="LLM_THINKING_BUDGET_TOKENS",
        label="Thinking Budget Tokens",
        description=("Token budget for extended thinking mode (advanced model)"),
        category=SettingCategory.LLM,
        setting_type=SettingType.INT,
        default_value="2048",
        min_value=0,
        max_value=100000,
        unit="tokens",
    ),
)

SETTINGS_REGISTRY.append(
    SettingDefinition(
        key="JWT_ALGORITHM",
        label="JWT Algorithm",
        description="Algorithm used for JWT signing",
        category=SettingCategory.SECURITY,
        setting_type=SettingType.STRING,
        default_value="HS256",
        is_readonly=True,
    ),
)

# Additional SYSTEM entries — problem types, integrations
SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="PROBLEM_TYPE_MANUAL_CREDIT_ADDITION",
            label="Manual Credit Addition Problem Type",
            description=("Problem type identifier for manual credit additions"),
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.STRING,
            default_value="manual_credit_addition",
        ),
        SettingDefinition(
            key="STORAGE_ACCOUNT_ID",
            label="Storage Account ID",
            description="Object storage account identifier",
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.STRING,
            default_value="",
        ),
        SettingDefinition(
            key="STORAGE_BUCKET",
            label="Storage Bucket",
            description="Object storage bucket name",
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.STRING,
            default_value="jaot-media",
        ),
        SettingDefinition(
            key="STORAGE_CDN_URL",
            label="Storage CDN URL",
            description="CDN URL for object storage",
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.STRING,
            default_value="",
        ),
        SettingDefinition(
            key="DISCOURSE_URL",
            label="Discourse URL",
            description="Discourse community forum URL",
            category=SettingCategory.SYSTEM,
            setting_type=SettingType.STRING,
            default_value="",
        ),
    ]
)


REGISTRY_BY_KEY: dict[str, SettingDefinition] = {s.key: s for s in SETTINGS_REGISTRY}

REGISTRY_BY_CATEGORY: dict[SettingCategory, list[SettingDefinition]] = {}
for _s in SETTINGS_REGISTRY:
    REGISTRY_BY_CATEGORY.setdefault(_s.category, []).append(_s)
