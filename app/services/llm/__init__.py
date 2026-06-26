"""LLM services for natural language to optimization formulation.

Provides: Anthropic client factory, formulation generation with streaming,
formulation validation, and content moderation.
"""

from app.services.llm.anthropic_client import (
    get_anthropic_client,
    get_anthropic_client_for_org,
)
from app.services.llm.chunked_generation import generate_formulation_chunked
from app.services.llm.explanation_service import explain_infeasibility, explain_solution
from app.services.llm.formulation_service import (
    generate_formulation,
    generate_formulation_resilient,
    generate_text_response,
    select_model,
)
from app.services.llm.moderation import moderate_message, report_flagged_message
from app.services.llm.validation import validate_formulation

__all__ = [
    "get_anthropic_client",
    "get_anthropic_client_for_org",
    "explain_solution",
    "explain_infeasibility",
    "generate_formulation",
    "generate_formulation_chunked",
    "generate_formulation_resilient",
    "generate_text_response",
    "select_model",
    "validate_formulation",
    "moderate_message",
    "report_flagged_message",
]
