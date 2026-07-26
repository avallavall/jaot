"""Declarative settings registry for admin configuration panel.

Maps every configurable setting to its type, constraints, category, and label.
This registry is the single source of truth for what settings exist and how they
should be validated. Adding a new runtime setting requires only adding a registry
entry here -- the frontend renders forms dynamically from the registry API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.version import APP_VERSION


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
        SettingDefinition(
            key="JAOT_DSL",
            label="JModel DSL (experimental)",
            description=(
                "When enabled, the studio exposes the JModel editor lens and the "
                "POST /dsl/compile endpoint that lowers the declarative DSL "
                "(sets / params / indexed families) to a flat optimization problem. "
                "Off by default; the feature ships dark."
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
            key="dsl_max_grounded_elements",
            label="JModel: Grounding Budget",
            description=(
                "Ceiling on the work one JModel compile may expand to (variables + "
                "constraint rows + summed terms). It exists to catch an accidental "
                "combinatorial blowup — a three-index family over large sets — before "
                "it pins a CPU, NOT to bound how large a legitimate model may be. "
                "Set 0 to remove the budget entirely and let the machine's memory be "
                "the only ceiling."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="2000000",
            min_value=0,
            max_value=None,
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
            description="Synchronous /solve wall-clock timeout in seconds (per execution)",
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="120",
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
            default_value="300",
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
                "Default is 2x the maximum per-request solver time limit (86400s)."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="172800",
            min_value=300,
            max_value=172800,
            unit="seconds",
        ),
        SettingDefinition(
            key="SENSITIVITY_MAX_RESOLVES",
            label="Sensitivity: Max Re-solves",
            description=(
                "Upper bound on how many re-solves one what-if batch (Sensitivity "
                "L2) may run. Each RHS-ranging or regret scenario is a FULL solve "
                "of a perturbed model, so this is the hard ceiling on the work an "
                "analysis request can queue."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="20",
            min_value=1,
            max_value=200,
        ),
        SettingDefinition(
            key="SENSITIVITY_TOP_CONSTRAINTS",
            label="Sensitivity: Ranged Constraints",
            description=(
                "How many binding constraints the what-if batch ranges. Each one "
                "costs two re-solves (relax and tighten), and relaxations run "
                "first so a batch cut short by the budget keeps the useful half."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="8",
            min_value=0,
            max_value=50,
        ),
        SettingDefinition(
            key="SENSITIVITY_TOP_DECISIONS",
            label="Sensitivity: Regret Decisions",
            description=(
                "How many binary decisions the what-if batch overrules to price "
                "the regret of deciding otherwise. One re-solve each; picks "
                "alternate between switched-on and switched-off decisions."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="4",
            min_value=0,
            max_value=50,
        ),
        SettingDefinition(
            key="SENSITIVITY_PER_SOLVE_MULTIPLIER",
            label="Sensitivity: Per-Solve Multiplier",
            description=(
                "Time limit for each what-if re-solve as a multiple of the "
                "ORIGINAL solve time (a model that took 4s gets 8s per scenario "
                "at 2.0), capped by SENSITIVITY_PER_SOLVE_CAP_SECONDS."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.FLOAT,
            default_value="2.0",
            min_value=0.1,
            max_value=20.0,
        ),
        SettingDefinition(
            key="SENSITIVITY_PER_SOLVE_CAP_SECONDS",
            label="Sensitivity: Per-Solve Cap",
            description=(
                "Hard ceiling on any single what-if re-solve, whatever the "
                "original solve took. Keeps one slow scenario from eating the "
                "whole batch budget."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="30",
            min_value=1,
            max_value=3600,
            unit="seconds",
        ),
        SettingDefinition(
            key="SENSITIVITY_TOTAL_BUDGET_SECONDS",
            label="Sensitivity: Batch Budget",
            description=(
                "Wall-clock budget for one what-if batch. When it runs out the "
                "remaining scenarios are returned as skipped and the analysis is "
                "flagged partial — never padded with guesses. Independent of the "
                "solve time limits: this bounds the ANALYSIS, not the solve."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="300",
            min_value=10,
            max_value=3600,
            unit="seconds",
        ),
        SettingDefinition(
            key="IIS_MAX_CONSTRAINTS",
            label="IIS: Max Constraints",
            description=(
                "Upper bound on the number of constraints for which the "
                "infeasibility explainer runs exact IIS computation (deletion "
                "filtering). Each constraint costs one extra re-solve, so the "
                "analysis is O(n) solves; above this cap it falls back to "
                "heuristic LLM-only reasoning over the formulation. P2."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="150",
            min_value=1,
            max_value=5000,
            unit="constraints",
        ),
        SettingDefinition(
            key="IIS_TIME_BUDGET_SECONDS",
            label="IIS: Time Budget",
            description=(
                "Wall-clock budget (seconds) for the deletion-filtering IIS "
                "search. When exceeded mid-search the analysis aborts and falls "
                "back to heuristic LLM-only reasoning. Each candidate re-solve "
                "also gets a tight per-solve time limit derived from this. P2."
            ),
            category=SettingCategory.SOLVER,
            setting_type=SettingType.INT,
            default_value="20",
            min_value=1,
            max_value=600,
            unit="seconds",
        ),
    ]
)

SETTINGS_REGISTRY.extend(
    [
        SettingDefinition(
            key="LLM_DEFAULT_MODEL",
            label="Default Model",
            description=(
                "Default LLM model for standard requests. Runs with thinking "
                "explicitly disabled — models from Sonnet 5 onwards think by "
                "default when the parameter is omitted, which would spend the "
                "output budget on reasoning instead of the answer."
            ),
            category=SettingCategory.LLM,
            setting_type=SettingType.STRING,
            default_value="claude-sonnet-5",
        ),
        SettingDefinition(
            key="LLM_ADVANCED_MODEL",
            label="Advanced Model",
            description=(
                "LLM model for advanced/complex requests. Runs with adaptive "
                "thinking at LLM_THINKING_EFFORT."
            ),
            category=SettingCategory.LLM,
            setting_type=SettingType.STRING,
            default_value="claude-opus-5",
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
            default_value="300",
            min_value=1,
            max_value=1000,
        ),
        SettingDefinition(
            key="LLM_RATE_LIMIT_PER_DAY",
            label="Rate Limit per Day",
            description="Max LLM requests per day",
            category=SettingCategory.LLM,
            setting_type=SettingType.INT,
            default_value="5000",
            min_value=1,
            max_value=100000,
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
            default_value="50.0",
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
                'from the real token usage returned by the API (W17). The "default" '
                "entry prices unknown/future models at Opus rates, so surprises "
                "over-estimate rather than under-estimate. Values are Anthropic USD "
                "list prices at ~1.08 USD/EUR; Sonnet 5 is priced at its list rate, "
                "not the lower introductory one."
            ),
            category=SettingCategory.LLM,
            setting_type=SettingType.JSON,
            default_value=(
                '{"claude-sonnet-5": {"input": 2.78, "output": 13.89}, '
                '"claude-opus-5": {"input": 4.63, "output": 23.15}, '
                '"claude-fable-5": {"input": 9.26, "output": 46.30}, '
                '"claude-sonnet-4-6": {"input": 2.78, "output": 13.89}, '
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
        SettingDefinition(
            key="AUTH_LOGIN_RATE_LIMIT_PER_MINUTE",
            label="Login Rate Limit per Minute",
            description=(
                "Max login attempts per minute (per IP and per API-key prefix) before "
                "a 429. Lower = stronger brute-force protection; higher = fewer false "
                "positives for shared IPs."
            ),
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="30",
            min_value=1,
            max_value=1000,
        ),
        SettingDefinition(
            key="AUTH_LOGIN_RATE_LIMIT_PER_DAY",
            label="Login Rate Limit per Day",
            description="Max login attempts per day (per IP and per API-key prefix) before a 429.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="300",
            min_value=1,
            max_value=100000,
        ),
        SettingDefinition(
            key="AUTH_SIGNUP_RATE_LIMIT_PER_MINUTE",
            label="Signup Rate Limit per Minute",
            description="Max signup attempts per minute (per IP) before a 429.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="10",
            min_value=1,
            max_value=1000,
        ),
        SettingDefinition(
            key="AUTH_SIGNUP_RATE_LIMIT_PER_DAY",
            label="Signup Rate Limit per Day",
            description="Max signup attempts per day (per IP) before a 429.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="50",
            min_value=1,
            max_value=100000,
        ),
        SettingDefinition(
            key="AUTH_VERIFY_EMAIL_RATE_LIMIT_PER_MINUTE",
            label="Verify-Email Rate Limit per Minute",
            description="Max email-verification attempts per minute (per token) before a 429.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="20",
            min_value=1,
            max_value=1000,
        ),
        SettingDefinition(
            key="AUTH_VERIFY_EMAIL_RATE_LIMIT_PER_DAY",
            label="Verify-Email Rate Limit per Day",
            description="Max email-verification attempts per day (per token) before a 429.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="100",
            min_value=1,
            max_value=100000,
        ),
        SettingDefinition(
            key="AUTH_PASSWORD_RESET_RATE_LIMIT_PER_HOUR",
            label="Password-Reset Rate Limit per Hour",
            description="Max password-reset emails per hour (per email address) before a 429.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="3",
            min_value=1,
            max_value=1000,
        ),
        SettingDefinition(
            key="AUTH_RESET_TOKEN_RATE_LIMIT_PER_MINUTE",
            label="Reset-Token Rate Limit per Minute",
            description="Max reset-password (token) attempts per minute before a 429.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="20",
            min_value=1,
            max_value=1000,
        ),
        SettingDefinition(
            key="AUTH_RESET_TOKEN_RATE_LIMIT_PER_DAY",
            label="Reset-Token Rate Limit per Day",
            description="Max reset-password (token) attempts per day before a 429.",
            category=SettingCategory.SECURITY,
            setting_type=SettingType.INT,
            default_value="100",
            min_value=1,
            max_value=100000,
        ),
    ]
)

# BILLING category — legacy tier LIMIT profiles (DEFAULT_PLAN + 4 tiers x 9 fields; ADR-008 removed all money settings)

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
# ADR-008: plan tiers are LIMIT PROFILES only — the credits/monthly_quota
# fields left with the credit system.
#
# No field has an upper bound any more. These caps were sized for a paid SaaS with
# tiers; on self-hosted open source an operator with big hardware must be able to
# type any number, and **0 means unlimited** for every one of them. The admin panel
# would otherwise refuse the value before it ever reached the DB.
_PLAN_FIELDS: list[tuple[str, str, SettingType, float | None, float | None, str | None]] = [
    # (field, label, type, min, max, unit) — max None = no ceiling, 0 = unlimited
    ("rate_limit_per_minute", "Rate Limit/Min", SettingType.INT, 0, None, None),
    ("rate_limit_per_day", "Rate Limit/Day", SettingType.INT, 0, None, None),
    (
        "max_solve_time_seconds",
        "Max Solve Time",
        SettingType.INT,
        0,
        None,
        "seconds",
    ),
    ("max_variables", "Max Variables", SettingType.INT, 0, None, None),
    ("max_daily_solves", "Max Daily Solves", SettingType.INT, 0, None, None),
    ("max_cron_schedules", "Max Cron Schedules", SettingType.INT, 0, None, None),
    ("allowed_features", "Allowed Features", SettingType.JSON, None, None, None),
]

_ALLOWED_FEATURES_DEFAULT = (
    '["llm_assistant","warm_start","sensitivity_analysis","cron_scheduling"]'
)

# Default values per tier, keyed by (tier, field)
_PLAN_DEFAULTS: dict[tuple[str, str], str] = {
    # Default plan ("free"): no paid tiers anymore — every signup gets full,
    # business-level access. Open-source self-hosted: business/usage limits
    # relaxed (solve time up to 24h, 100k daily solves). The platform-wide
    # monthly LLM budget remains the only real cost ceiling. Mirrored here so
    # fresh installs / DB reseeds match. (starter/pro/business kept as legacy,
    # also relaxed for consistency.)
    ("free", "rate_limit_per_minute"): "120",
    ("free", "rate_limit_per_day"): "50000",
    ("free", "max_solve_time_seconds"): "0",
    ("free", "max_variables"): "0",
    ("free", "max_daily_solves"): "0",
    ("free", "max_cron_schedules"): "0",
    ("free", "allowed_features"): _ALLOWED_FEATURES_DEFAULT,
    # Starter tier
    ("starter", "rate_limit_per_minute"): "20",
    ("starter", "rate_limit_per_day"): "500",
    ("starter", "max_solve_time_seconds"): "0",
    ("starter", "max_variables"): "0",
    ("starter", "max_daily_solves"): "0",
    ("starter", "max_cron_schedules"): "0",
    ("starter", "allowed_features"): _ALLOWED_FEATURES_DEFAULT,
    # Pro tier
    ("pro", "rate_limit_per_minute"): "60",
    ("pro", "rate_limit_per_day"): "5000",
    ("pro", "max_solve_time_seconds"): "0",
    ("pro", "max_variables"): "0",
    ("pro", "max_daily_solves"): "0",
    ("pro", "max_cron_schedules"): "0",
    ("pro", "allowed_features"): _ALLOWED_FEATURES_DEFAULT,
    # Business tier
    ("business", "rate_limit_per_minute"): "120",
    ("business", "rate_limit_per_day"): "50000",
    ("business", "max_solve_time_seconds"): "0",
    ("business", "max_variables"): "0",
    ("business", "max_daily_solves"): "0",
    ("business", "max_cron_schedules"): "0",
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


# SECRETS category (all readonly, masked)

_SECRET_KEYS = [
    ("DATABASE_URL", "Database URL", "PostgreSQL connection string"),
    ("JWT_SECRET", "JWT Secret", "Secret key for JWT signing"),
    ("ANTHROPIC_API_KEY", "Anthropic API Key", "API key for Claude LLM"),
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
            default_value=APP_VERSION,
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
        SettingDefinition(
            key="RAG_RERANKER_ENABLED",
            label="Reranker Enabled",
            description=(
                "Re-rank retrieved candidates with a local cross-encoder before "
                "selecting the top-K (improves precision; adds CPU latency). The model "
                "must be present in the image — see RAG_RERANKER_MODEL."
            ),
            category=SettingCategory.RAG,
            setting_type=SettingType.BOOL,
            default_value="false",
        ),
        SettingDefinition(
            key="RAG_RERANKER_MODEL",
            label="Reranker Model",
            description=(
                "sentence-transformers CrossEncoder model for reranking. The default is "
                "pre-downloaded in the image; a non-default value requires a rebuild that "
                "bakes it in (the runtime filesystem is read-only)."
            ),
            category=SettingCategory.RAG,
            setting_type=SettingType.STRING,
            default_value="cross-encoder/ms-marco-MiniLM-L-6-v2",
        ),
    ]
)

SETTINGS_REGISTRY.append(
    SettingDefinition(
        key="LLM_THINKING_BUDGET_TOKENS",
        label="Thinking Budget Tokens (deprecated)",
        description=(
            "DEPRECATED and unused. Manual extended thinking "
            '({"type": "enabled", "budget_tokens": N}) is rejected with a 400 '
            "by every model from Opus 4.7 / Sonnet 5 onwards. The advanced "
            "model now uses adaptive thinking; control its depth with "
            "LLM_THINKING_EFFORT. Kept only because settings rows are removed "
            "one release after the code that reads them."
        ),
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
        key="LLM_THINKING_EFFORT",
        label="Thinking Effort",
        description=(
            "Reasoning depth for the advanced model's adaptive thinking, and "
            "the replacement for LLM_THINKING_BUDGET_TOKENS. One of: low, "
            "medium, high, xhigh, max — higher means deeper reasoning at more "
            "tokens and latency. An unrecognised value falls back to 'high' "
            "(the API default) rather than failing the request."
        ),
        category=SettingCategory.LLM,
        setting_type=SettingType.STRING,
        default_value="high",
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

# Additional SYSTEM entries — integrations
SETTINGS_REGISTRY.extend(
    [
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
