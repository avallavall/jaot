"""B3 — generate a JModel source from a description (+ vision) with a compile loop.

The inverse of everything else in the DSL lens: instead of compiling or rendering a
source the user wrote, this *writes* one. It is a **service** (not the pure ``app.domains.dsl``
compiler) because it needs both the compiler AND the Anthropic client — the same
``app.services → app.domains.*`` direction ``jmodel_deground`` already relies on.

The design turns JModel's determinism into a self-correcting loop: the LLM proposes a
source, the compiler is the oracle, and any structured compile error is fed straight back
for a retry. Honest by construction — the caller only advertises ``ok=True`` when the
returned source VERIFIABLY compiles; otherwise it hands back the best-effort draft plus
the last compile error so the user lands on an editable starting point, never a fake.

No RAG round-trip here: the grammar and a few canonical exemplars live in the system
prompt (``JMODEL_GENERATION_SYSTEM_PROMPT``), which for a compact DSL is more reliable
than similarity-retrieved snippets. Attachments ride as Claude's native vision blocks
(images + PDFs), so a screenshot of a thesis formulation is read directly — no OCR.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.domains.dsl import JModelError, compile_jmodel
from app.schemas.dsl import (
    DSL_GENERATE_MEDIA_TYPES,
    DSL_GENERATE_PDF_TYPE,
    DSLGenerateAttachment,
)
from app.services.llm.anthropic_client import collect_text
from app.services.llm.prompt_templates import (
    JMODEL_GENERATION_RETRY_TEMPLATE,
    JMODEL_GENERATION_SYSTEM_PROMPT,
)
from app.services.llm.thinking import apply_thinking

logger = logging.getLogger(__name__)

# How many generate→compile rounds before we give up and return the best-effort draft.
# 1 initial + 2 corrections: empirically the model fixes almost every miss on the first
# retry once it sees the exact compiler error and position.
MAX_ATTEMPTS = 3

# A fenced block with ANY language label (```jmodel, but a model may slip ```text or
# even ```python) or bare ```; the label only counts when it sits alone on the fence
# line, so an inline `` ```var x;``` `` still captures from the first character.
# DOTALL so the capture spans the whole source.
_FENCE_RE = re.compile(r"```(?:[a-zA-Z]*[ \t]*\r?\n)?(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class GenerateOutcome:
    """The result of an AI generation run — mirrors ``DSLGenerateResponse`` + token usage.

    ``ok`` means ``source`` compiled. When false, ``source`` is still the last draft the
    model produced (editable) and ``error_message`` names why it did not compile. Token
    counts sum across every attempt so the caller can price the whole run.
    """

    ok: bool
    source: str | None
    error_message: str | None
    error_position: int | None
    attempts: int
    input_tokens: int
    output_tokens: int


def extract_jmodel_source(text: str) -> str:
    """Pull the JModel source out of the model's reply.

    Prefers the first fenced code block (the contract asks for exactly one ```jmodel
    block); falls back to the whole reply stripped, so a model that forgets the fence
    still feeds *something* to the compiler (which then judges it).
    """
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _build_first_turn(
    description: str,
    attachments: list[DSLGenerateAttachment],
    current_source: str | None,
) -> list[dict[str, Any]]:
    """Assemble the first user turn: instruction text + native vision blocks.

    Returns Anthropic content blocks. Images become ``image`` blocks and PDFs
    ``document`` blocks (Claude reads both natively), preceded by a text block that
    frames the task and, when refining, quotes the existing draft.
    """
    lines: list[str] = []
    if current_source and current_source.strip():
        lines.append(
            "Refine this existing JModel draft based on the request below "
            "(keep what is correct, change only what the request needs):\n"
            f"```jmodel\n{current_source.strip()}\n```"
        )
    if description.strip():
        lines.append(description.strip())
    elif attachments:
        # Image/PDF-only: the attachment carries the whole formulation.
        lines.append(
            "Write the JModel source for the optimization problem shown in the "
            "attached image(s)/PDF."
        )

    blocks: list[dict[str, Any]] = [{"type": "text", "text": "\n\n".join(lines)}]
    for att in attachments:
        if att.media_type not in DSL_GENERATE_MEDIA_TYPES:
            # Defensive: the schema/route validate this, but never forward an
            # unexpected media type to the API.
            continue
        if att.media_type == DSL_GENERATE_PDF_TYPE:
            blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": att.media_type,
                        "data": att.data,
                    },
                }
            )
        else:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": att.media_type,
                        "data": att.data,
                    },
                }
            )
    return blocks


def _retry_turn(exc: JModelError, source: str) -> str:
    """Build the follow-up user turn that feeds a compile failure back to the model."""
    position = f" (position {exc.position})" if exc.position is not None else ""
    snippet = ""
    if exc.position is not None and 0 <= exc.position <= len(source):
        start = max(0, exc.position - 40)
        end = min(len(source), exc.position + 40)
        snippet = f"Near: …{source[start:end]}…\n"
    return JMODEL_GENERATION_RETRY_TEMPLATE.format(
        message=exc.message, position=position, snippet=snippet
    )


async def generate_jmodel(
    *,
    client: Any,
    model: str,
    max_tokens: int,
    description: str,
    attachments: list[DSLGenerateAttachment],
    current_source: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> GenerateOutcome:
    """Generate a JModel source, retrying against the compiler until it compiles.

    Args:
        client: An ``AsyncAnthropic`` client (BYOK-resolved or platform).
        model: Model id to call.
        max_tokens: Output-token cap per attempt (JModel sources are small).
        description: The user's plain-language problem description (may be empty when
            attachments carry the formulation).
        attachments: Vision attachments (validated images/PDFs).
        current_source: An existing draft to refine, if any.
        max_attempts: Total generate→compile rounds before giving up.

    Returns:
        A :class:`GenerateOutcome`. Never raises for a *modeling* failure (that is
        ``ok=False`` + the compile error); it may raise on an Anthropic transport error,
        which the route classifies.
    """
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _build_first_turn(description, attachments, current_source)}
    ]

    last_source: str | None = None
    last_msg: str | None = None
    last_pos: int | None = None
    total_in = 0
    total_out = 0
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        request_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": JMODEL_GENERATION_SYSTEM_PROMPT,
            "messages": messages,
        }
        # The compile-retry loop is the oracle here, so reasoning buys nothing —
        # and left unset it would eat the (deliberately small) output budget.
        apply_thinking(request_kwargs, thinking=False)
        response = await client.messages.create(**request_kwargs)
        usage = getattr(response, "usage", None)
        total_in += int(getattr(usage, "input_tokens", 0) or 0)
        total_out += int(getattr(usage, "output_tokens", 0) or 0)

        raw_text = collect_text(response)
        source = extract_jmodel_source(raw_text)
        last_source = source

        try:
            compile_jmodel(source)
        except JModelError as exc:
            last_msg, last_pos = exc.message, exc.position
            logger.info(
                "JModel AI generation attempt %d/%d did not compile: %s",
                attempt,
                max_attempts,
                exc.message,
                extra={"event_code": "dsl.generate_compile_error"},
            )
            if attempt < max_attempts:
                # The Anthropic API rejects an empty content block — a (rare)
                # text-less reply must still yield a valid assistant turn.
                messages.append({"role": "assistant", "content": raw_text or "(no output)"})
                messages.append({"role": "user", "content": _retry_turn(exc, source)})
            continue
        except Exception:
            # A non-JModelError from the compiler is a compiler bug, not user error.
            # Don't burn retries on it; surface an honest failure with the draft intact.
            logger.exception("JModel compiler crashed while validating AI-generated source")
            return GenerateOutcome(
                ok=False,
                source=source,
                error_message="internal compiler error",
                error_position=None,
                attempts=attempt,
                input_tokens=total_in,
                output_tokens=total_out,
            )
        else:
            return GenerateOutcome(
                ok=True,
                source=source,
                error_message=None,
                error_position=None,
                attempts=attempt,
                input_tokens=total_in,
                output_tokens=total_out,
            )

    return GenerateOutcome(
        ok=False,
        source=last_source,
        error_message=last_msg,
        error_position=last_pos,
        attempts=attempt,
        input_tokens=total_in,
        output_tokens=total_out,
    )
