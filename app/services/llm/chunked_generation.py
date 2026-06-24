"""Chunked generation for very large optimization problems.

When retry strategies are exhausted, splits generation into two chunks:
1. Variables + objective (VariablesChunk schema)
2. Constraints (ConstraintsChunk schema, with variables context)

Then assembles into a complete Formulation.
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.schemas.llm import (
    CONSTRAINTS_CHUNK_SCHEMA,
    VARIABLES_CHUNK_SCHEMA,
    ConstraintsChunk,
    Formulation,
    VariablesChunk,
)
from app.services.llm.anthropic_client import get_anthropic_client
from app.services.llm.errors import LLMStatusCode
from app.services.llm.prompt_templates import FORMULATION_SYSTEM_PROMPT
from app.services.llm.validation import validate_formulation

logger = logging.getLogger(__name__)

VARIABLES_SYSTEM_PROMPT = (
    FORMULATION_SYSTEM_PROMPT
    + """

IMPORTANT: For this request, output ONLY the problem_name, summary, variables, and objective.
Do NOT include constraints. Constraints will be generated separately."""
)

CONSTRAINTS_SYSTEM_PROMPT = (
    FORMULATION_SYSTEM_PROMPT
    + """

IMPORTANT: For this request, output ONLY the constraints list.
Use EXACTLY the variable names provided in the context below.
Do NOT rename or introduce new variables."""
)


def _assemble_formulation(
    vars_chunk: dict[str, Any],
    constraints_chunk: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine variable and constraint chunks into a complete Formulation dict."""
    return {
        "problem_name": vars_chunk["problem_name"],
        "summary": vars_chunk["summary"],
        "variables": vars_chunk["variables"],
        "constraints": constraints_chunk["constraints"] if constraints_chunk else [],
        "objective": vars_chunk["objective"],
    }


async def _generate_chunk(
    messages: list[dict[str, Any]],
    model: str,
    schema: dict[str, Any],
    system_prompt: str,
    max_tokens: int = 16000,
    thinking: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, int] | None]:
    """Generate a single chunk using non-streaming API call.

    Returns ``(parsed_json_or_None, usage_or_None)``. Usage (W17) is
    extracted before JSON parsing so a parse failure still reports the
    tokens that were billed for the attempt.
    """
    client = get_anthropic_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": messages,
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }

    if thinking:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": 2048}

    usage: dict[str, int] | None = None
    try:
        response = await client.messages.create(**kwargs)
        resp_usage = getattr(response, "usage", None)
        if resp_usage is not None:
            _in = getattr(resp_usage, "input_tokens", None)
            _out = getattr(resp_usage, "output_tokens", None)
            usage = {
                "input_tokens": _in if isinstance(_in, int) else 0,
                "output_tokens": _out if isinstance(_out, int) else 0,
            }
        text = response.content[0].text
        result: dict[str, Any] = json.loads(text)
        return result, usage
    except Exception as e:
        logger.error(
            "Chunk generation failed: %s",
            e,
            exc_info=True,
            extra={"event_code": "llm.chunk_generation_failed"},
        )
        return None, usage


async def generate_formulation_chunked(
    messages: list[dict[str, Any]],
    model: str,
    thinking: bool = False,
) -> AsyncGenerator[dict[str, Any], None]:
    """Generate a formulation in chunks for very large problems.

    Splits into variables+objective and constraints chunks, then assembles.

    Yields:
        chunk_progress, formulation/partial_result, validation_errors, done events.
    """
    # --- Chunk 1: Variables + Objective ---
    yield {"type": "status", "code": LLMStatusCode.GENERATING_VARIABLES}

    vars_chunk, usage = await _generate_chunk(
        messages, model, VARIABLES_CHUNK_SCHEMA, VARIABLES_SYSTEM_PROMPT, thinking=thinking
    )
    if usage:
        # W17: internal cost-tracking event — every chunk call is billed,
        # including retries. Consumed by the SSE endpoint, never forwarded.
        yield {"type": "usage", "model": model, **usage}

    if vars_chunk is None:
        # Retry once
        vars_chunk, usage = await _generate_chunk(
            messages, model, VARIABLES_CHUNK_SCHEMA, VARIABLES_SYSTEM_PROMPT, thinking=thinking
        )
        if usage:
            yield {"type": "usage", "model": model, **usage}

    if vars_chunk is None:
        # Total failure — can't even generate variables
        yield {
            "type": "partial_result",
            "data": {
                "problem_name": "generation_failed",
                "summary": "Failed to generate formulation. Try simplifying the problem.",
                "variables": [],
                "constraints": [],
                "objective": {
                    "sense": "minimize",
                    "expression": "0",
                    "description": "Generation failed",
                },
            },
            "warning": "This problem is too complex for automatic formulation. Try breaking it into smaller sub-problems.",
        }
        yield {"type": "done"}
        return

    try:
        VariablesChunk.model_validate(vars_chunk)
    except Exception as e:
        logger.warning("Variables chunk validation failed: %s", e)

    # --- Chunk 2: Constraints ---
    yield {"type": "status", "code": LLMStatusCode.GENERATING_CONSTRAINTS}

    # Inject variables context into messages so constraints reference correct variable names
    constraint_messages = messages + [
        {
            "role": "assistant",
            "content": f"Here are the variables and objective I've defined:\n```json\n{json.dumps(vars_chunk, indent=2)}\n```\nNow I will generate the constraints using these exact variable names.",
        },
        {
            "role": "user",
            "content": "Generate the constraints for this problem using the exact variable names above.",
        },
    ]

    constraints_chunk, usage = await _generate_chunk(
        constraint_messages,
        model,
        CONSTRAINTS_CHUNK_SCHEMA,
        CONSTRAINTS_SYSTEM_PROMPT,
        thinking=thinking,
    )
    if usage:
        yield {"type": "usage", "model": model, **usage}

    if constraints_chunk is None:
        # Retry once
        constraints_chunk, usage = await _generate_chunk(
            constraint_messages,
            model,
            CONSTRAINTS_CHUNK_SCHEMA,
            CONSTRAINTS_SYSTEM_PROMPT,
            thinking=thinking,
        )
        if usage:
            yield {"type": "usage", "model": model, **usage}

    if constraints_chunk is not None:
        try:
            ConstraintsChunk.model_validate(constraints_chunk)
        except Exception as e:
            logger.warning("Constraints chunk validation failed: %s", e)
            constraints_chunk = None

    # --- Assembly ---
    yield {"type": "status", "code": LLMStatusCode.ASSEMBLING}

    formulation_dict = _assemble_formulation(vars_chunk, constraints_chunk)

    if constraints_chunk is None:
        yield {
            "type": "partial_result",
            "data": formulation_dict,
            "warning": "Constraints could not be generated. Variables and objective are ready — try adding constraints manually or simplify the problem.",
        }
    else:
        try:
            Formulation.model_validate(formulation_dict)
        except Exception as e:
            logger.warning("Assembled formulation validation failed: %s", e)

        yield {"type": "formulation", "data": formulation_dict}

    # Run validation checks
    errors = validate_formulation(formulation_dict)
    if errors:
        yield {"type": "validation_errors", "data": errors}

    yield {"type": "done"}
