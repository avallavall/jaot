"""Solution-explanation service using Anthropic Claude.

Streams a plain-language explanation of a *solved* optimization model: what the
solution says to do, why (binding constraints + shadow prices), and concrete
what-if levers (reduced costs / ranging). Reuses the chat streaming machinery in
``formulation_service.generate_text_response`` — this module only assembles the
grounded user turn and the solution-explanation system prompt.

The explanation is strictly grounded in the formulation / solution / sensitivity
passed in: the system prompt forbids inventing numbers, and the user turn embeds
the exact values as JSON so there is nothing to hallucinate.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.services.llm.errors import LLMStatusCode
from app.services.llm.formulation_service import generate_text_response
from app.services.llm.prompt_templates import (
    SOLUTION_EXPLANATION_SYSTEM_PROMPT,
    build_solution_explanation_prompt,
)

logger = logging.getLogger(__name__)


async def explain_solution(
    messages: list[dict[str, Any]],
    formulation: dict[str, Any] | None,
    solution: dict[str, Any] | None,
    sensitivity: dict[str, Any] | None,
    model: str,
    *,
    thinking: bool = False,
    rag_context: str | None = None,
    db: Any | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream a plain-language explanation of a solved optimization model.

    Builds a single grounded user turn (formulation + solution + sensitivity),
    appends it to any prior conversation ``messages``, and delegates to
    ``generate_text_response`` with the solution-explanation system prompt.

    Yields the same event shapes as ``generate_text_response``:
    - {"type": "status", "code": LLMStatusCode.EXPLAINING} once at the start
    - {"type": "delta", "text": "..."} for each text chunk
    - {"type": "usage", ...} internal token accounting (consumed by the endpoint)
    - {"type": "error", "code": LLMErrorCode} on upstream failure
    - {"type": "done"} when finished

    Args:
        messages: Prior conversation turns (Anthropic message dicts); may be empty.
        formulation: The model formulation dict (variables/constraints/objective).
        solution: Variable values + objective for the solved model.
        sensitivity: Sensitivity analysis dict (constraints/variables/ranges) or None.
        model: Model ID to use (e.g. "claude-sonnet-4-6").
        thinking: Whether to enable extended thinking.
        rag_context: Optional pre-formatted optimization-knowledge block appended
            to the system prompt.
        db: Optional DB session for runtime settings.
    """
    # Surface an "explaining" status so the UI shows a thinking indicator while the
    # first token streams. Stable enum code — the endpoint forwards it verbatim.
    yield {"type": "status", "code": LLMStatusCode.EXPLAINING}

    user_turn = build_solution_explanation_prompt(formulation, solution, sensitivity)
    explain_messages = [*messages, {"role": "user", "content": user_turn}]

    system_prompt = SOLUTION_EXPLANATION_SYSTEM_PROMPT
    if rag_context:
        system_prompt = f"{system_prompt}{rag_context}"

    async for event in generate_text_response(
        explain_messages,
        model,
        thinking=thinking,
        system_prompt=system_prompt,
        db=db,
    ):
        yield event
