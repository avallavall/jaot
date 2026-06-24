"""Event type constants for feature usage analytics.

All event types follow the domain.action naming convention.
"""

USER_SIGNUP = "user.signup"
USER_LOGIN = "user.login"
ORG_CREATE = "org.create"


SOLVER_SOLVE = "solver.solve"


MODEL_CREATE = "model.create"


AI_BUILDER_MESSAGE = "ai_builder.message"


MCP_TOOL_CALL = "mcp.tool_call"


TEMPLATE_USE = "template.use"


MARKETPLACE_PURCHASE = "marketplace.purchase"
MARKETPLACE_ACTIVATE = "marketplace.activate"
MARKETPLACE_PUBLISH = "marketplace.publish"


SCHEDULE_CREATE = "schedule.create"


CREDIT_WITHDRAWAL = "credit.withdrawal"


PLACEMENT_PURCHASE = "placement.purchase"


ALL_EVENT_TYPES: list[str] = [
    USER_SIGNUP,
    USER_LOGIN,
    ORG_CREATE,
    SOLVER_SOLVE,
    MODEL_CREATE,
    AI_BUILDER_MESSAGE,
    MCP_TOOL_CALL,
    TEMPLATE_USE,
    MARKETPLACE_PURCHASE,
    MARKETPLACE_ACTIVATE,
    MARKETPLACE_PUBLISH,
    SCHEDULE_CREATE,
    CREDIT_WITHDRAWAL,
    PLACEMENT_PURCHASE,
]


EVENT_DOMAINS: dict[str, list[str]] = {
    "Solver": [SOLVER_SOLVE, TEMPLATE_USE],
    "AI Builder": [AI_BUILDER_MESSAGE],
    "Marketplace": [MARKETPLACE_PURCHASE, MARKETPLACE_ACTIVATE, MARKETPLACE_PUBLISH],
    "MCP": [MCP_TOOL_CALL],
    "Scheduling": [SCHEDULE_CREATE],
    "Credits": [CREDIT_WITHDRAWAL, PLACEMENT_PURCHASE],
}


FUNNEL_STEPS: list[str] = [
    USER_SIGNUP,
    MODEL_CREATE,
    SOLVER_SOLVE,
    MARKETPLACE_PURCHASE,
]
