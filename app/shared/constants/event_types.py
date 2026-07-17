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


# "marketplace.activate" = adoption: a "Use in studio" fork of a listing
# (wire value predates the P1.5 fusion and is kept for analytics continuity).
MARKETPLACE_ACTIVATE = "marketplace.activate"
MARKETPLACE_PUBLISH = "marketplace.publish"


SCHEDULE_CREATE = "schedule.create"


# ADR-008: credit.withdrawal / placement.purchase / marketplace.purchase event
# types removed with the money layer (never emitted again; no dead "Credits"
# analytics domain, no dead purchase funnel step).

ALL_EVENT_TYPES: list[str] = [
    USER_SIGNUP,
    USER_LOGIN,
    ORG_CREATE,
    SOLVER_SOLVE,
    MODEL_CREATE,
    AI_BUILDER_MESSAGE,
    MCP_TOOL_CALL,
    TEMPLATE_USE,
    MARKETPLACE_ACTIVATE,
    MARKETPLACE_PUBLISH,
    SCHEDULE_CREATE,
]


EVENT_DOMAINS: dict[str, list[str]] = {
    "Solver": [SOLVER_SOLVE, TEMPLATE_USE],
    "AI Builder": [AI_BUILDER_MESSAGE],
    "Marketplace": [MARKETPLACE_ACTIVATE, MARKETPLACE_PUBLISH],
    "MCP": [MCP_TOOL_CALL],
    "Scheduling": [SCHEDULE_CREATE],
}


FUNNEL_STEPS: list[str] = [
    USER_SIGNUP,
    MODEL_CREATE,
    SOLVER_SOLVE,
    MARKETPLACE_ACTIVATE,
]
