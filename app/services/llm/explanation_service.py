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
from dataclasses import dataclass
from typing import Any

from app.services.llm.anthropic_client import collect_text
from app.services.llm.errors import LLMStatusCode
from app.services.llm.formulation_service import generate_text_response
from app.services.llm.language import language_directive
from app.services.llm.prompt_templates import (
    INFEASIBILITY_EXPLANATION_SYSTEM_PROMPT,
    MODEL_DIFF_EXPLANATION_SYSTEM_PROMPT,
    MODEL_EXPLANATION_SYSTEM_PROMPT,
    SCENARIO_EXPLANATION_SYSTEM_PROMPT,
    SOLUTION_EXPLANATION_SYSTEM_PROMPT,
    build_infeasibility_explanation_prompt,
    build_model_explanation_prompt,
    build_scenario_explanation_prompt,
    build_solution_explanation_prompt,
    build_version_diff_prompt,
)
from app.services.llm.thinking import apply_thinking

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
    locale: str | None = None,
    client: Any | None = None,
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
        model: Model ID to use (e.g. "claude-sonnet-5").
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
    system_prompt += language_directive(locale)

    async for event in generate_text_response(
        explain_messages,
        model,
        thinking=thinking,
        system_prompt=system_prompt,
        client=client,
        db=db,
    ):
        yield event


async def explain_infeasibility(
    messages: list[dict[str, Any]],
    formulation: dict[str, Any] | None,
    infeasibility: dict[str, Any] | None,
    model: str,
    *,
    thinking: bool = False,
    rag_context: str | None = None,
    locale: str | None = None,
    client: Any | None = None,
    db: Any | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream a plain-language explanation of WHY a model is INFEASIBLE.

    Builds a single grounded user turn (formulation + IIS analysis), appends it to
    any prior ``messages``, and delegates to ``generate_text_response`` with the
    infeasibility-explanation system prompt. Mirrors ``explain_solution`` exactly so
    the SSE event contract and credit accounting stay identical.

    When ``infeasibility`` carries an exact IIS (``method="iis"`` with members) the
    explanation is grounded in those specific conflicting constraints/bounds.
    Otherwise the prompt asks for a clearly-flagged heuristic diagnosis over the
    formulation.

    Yields the same event shapes as ``generate_text_response``:
    - {"type": "status", "code": LLMStatusCode.EXPLAINING} once at the start
    - {"type": "delta", "text": "..."} for each text chunk
    - {"type": "usage", ...} internal token accounting (consumed by the endpoint)
    - {"type": "error", "code": LLMErrorCode} on upstream failure
    - {"type": "done"} when finished

    Args:
        messages: Prior conversation turns (Anthropic message dicts); may be empty.
        formulation: The model formulation dict (variables/constraints/objective).
        infeasibility: The IIS analysis dict (iis_constraints / iis_variable_bounds /
            conflict_type / method / note) or None for heuristic-only reasoning.
        model: Model ID to use (e.g. "claude-sonnet-5").
        thinking: Whether to enable extended thinking.
        rag_context: Optional pre-formatted optimization-knowledge block appended
            to the system prompt.
        db: Optional DB session for runtime settings.
    """
    # Reuse the EXPLAINING status (P1) — no new event code, so the parity test stays
    # green. The endpoint forwards it verbatim to show a thinking indicator.
    yield {"type": "status", "code": LLMStatusCode.EXPLAINING}

    user_turn = build_infeasibility_explanation_prompt(formulation, infeasibility)
    explain_messages = [*messages, {"role": "user", "content": user_turn}]

    system_prompt = INFEASIBILITY_EXPLANATION_SYSTEM_PROMPT
    if rag_context:
        system_prompt = f"{system_prompt}{rag_context}"
    system_prompt += language_directive(locale)

    async for event in generate_text_response(
        explain_messages,
        model,
        thinking=thinking,
        system_prompt=system_prompt,
        client=client,
        db=db,
    ):
        yield event


async def explain_model(
    messages: list[dict[str, Any]],
    formulation: dict[str, Any] | None,
    stats: dict[str, Any] | None,
    model: str,
    *,
    thinking: bool = False,
    rag_context: str | None = None,
    locale: str | None = None,
    client: Any | None = None,
    db: Any | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream a plain-language explanation of an optimization MODEL (not yet solved).

    Builds a single grounded user turn (formulation + the Python-computed
    ``ModelStats``), appends it to any prior ``messages``, and delegates to
    ``generate_text_response`` with the model-explanation system prompt. Mirrors
    ``explain_solution`` exactly so the SSE event contract and credit accounting stay
    identical. The statistics are authoritative, so the model has nothing to invent.

    Args:
        messages: Prior conversation turns (Anthropic message dicts); may be empty.
        formulation: The model formulation dict (variables/constraints/objective).
        stats: The serialized ``ModelStats`` (counts, problem class, health, warnings).
        model: Model ID to use (e.g. "claude-sonnet-5").
        thinking: Whether to enable extended thinking.
        rag_context: Optional pre-formatted optimization-knowledge block.
        db: Optional DB session for runtime settings.
    """
    # Reuse the EXPLAINING status (P1) — no new event code, so the parity test stays green.
    yield {"type": "status", "code": LLMStatusCode.EXPLAINING}

    user_turn = build_model_explanation_prompt(formulation, stats)
    explain_messages = [*messages, {"role": "user", "content": user_turn}]

    system_prompt = MODEL_EXPLANATION_SYSTEM_PROMPT
    if rag_context:
        system_prompt = f"{system_prompt}{rag_context}"
    system_prompt += language_directive(locale)

    async for event in generate_text_response(
        explain_messages,
        model,
        thinking=thinking,
        system_prompt=system_prompt,
        client=client,
        db=db,
    ):
        yield event


async def explain_version_diff(
    messages: list[dict[str, Any]],
    old_problem: dict[str, Any] | None,
    new_problem: dict[str, Any] | None,
    structural_diff: dict[str, Any] | None,
    old_summary: str | None,
    new_summary: str | None,
    model: str,
    *,
    thinking: bool = False,
    rag_context: str | None = None,
    locale: str | None = None,
    client: Any | None = None,
    db: Any | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream a plain-language narration of the CHANGE between two model versions.

    The diff is computed in Python (``model_project_service.diff_versions``) and
    passed in as ``structural_diff``; the LLM only verbalizes it — it is told to
    narrate ONLY changes present in the diff, so the "explain the change" feature is
    hallucination-proof. Mirrors ``explain_solution`` for the SSE/credit contract.

    Args:
        messages: Prior conversation turns; may be empty.
        old_problem / new_problem: The two version snapshots' model_json (context).
        structural_diff: The authoritative pre-computed diff (added/removed/modified
            vars & constraints + objective change).
        old_summary / new_summary: Each version's commit summary.
        model: Model ID to use.
    """
    yield {"type": "status", "code": LLMStatusCode.EXPLAINING}

    user_turn = build_version_diff_prompt(
        old_problem, new_problem, structural_diff, old_summary, new_summary
    )
    explain_messages = [*messages, {"role": "user", "content": user_turn}]

    system_prompt = MODEL_DIFF_EXPLANATION_SYSTEM_PROMPT
    if rag_context:
        system_prompt = f"{system_prompt}{rag_context}"
    system_prompt += language_directive(locale)

    async for event in generate_text_response(
        explain_messages,
        model,
        thinking=thinking,
        system_prompt=system_prompt,
        client=client,
        db=db,
    ):
        yield event


@dataclass(frozen=True)
class ScenarioExplanationOutcome:
    """A finished what-if explanation plus what it cost to produce."""

    text: str
    input_tokens: int
    output_tokens: int


async def explain_scenarios(
    *,
    client: Any,
    model: str,
    max_tokens: int,
    analysis: dict[str, Any],
    formulation: dict[str, Any] | None = None,
    locale: str | None = None,
) -> ScenarioExplanationOutcome:
    """Explain a measured what-if analysis (Sensitivity L2) in plain language.

    Deliberately NOT streamed, unlike its siblings above: the answer is a few
    sentences, and it is cached on the execution so a reload costs nothing. A
    single request/response keeps the caller free to persist the text before it
    ever reaches the client.

    Thinking stays off — narrating numbers that are already computed needs none,
    and since Sonnet 5 an unset ``thinking`` means "think", which would eat the
    (deliberately small) output budget.
    """
    request_kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": SCENARIO_EXPLANATION_SYSTEM_PROMPT + language_directive(locale),
        "messages": [
            {"role": "user", "content": build_scenario_explanation_prompt(analysis, formulation)}
        ],
    }
    apply_thinking(request_kwargs, thinking=False)
    response = await client.messages.create(**request_kwargs)
    usage = getattr(response, "usage", None)
    return ScenarioExplanationOutcome(
        text=collect_text(response).strip(),
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )
