"""Unit tests for the B3 JModel AI-generation loop (``app.services.jmodel_generate``).

Pure (no DB, no network): a fake Anthropic client feeds canned replies so we exercise
the generate→compile→feed-error→retry loop, source extraction, token accounting, and
vision-block assembly deterministically. Also guards that the exemplars baked into the
system prompt actually compile — a broken exemplar would teach the model wrong syntax.
"""

from __future__ import annotations

import re

import pytest

from app.domains.dsl import JModelError, compile_jmodel
from app.schemas.dsl import DSLGenerateAttachment
from app.services.jmodel_generate import (
    _build_first_turn,
    extract_jmodel_source,
    generate_jmodel,
)
from app.services.llm.prompt_templates import JMODEL_GENERATION_SYSTEM_PROMPT

GOOD = (
    "```jmodel\n"
    "set I := {a, b};\n"
    "param w{I} := a 2, b 3;\n"
    "var x{I} binary;\n"
    "maximize obj: sum{i in I} w[i] * x[i];\n"
    "subject to pick: sum{i in I} x[i] <= 1;\n"
    "```"
)
# Missing ';' after 'binary' -> a real compile error the model must fix.
BROKEN = "```jmodel\nvar x binary\nmaximize obj: x;\n```"


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Usage:
    def __init__(self, i: int, o: int) -> None:
        self.input_tokens = i
        self.output_tokens = o


class _Resp:
    def __init__(self, text: str, i: int = 100, o: int = 50) -> None:
        self.content = [_Block(text)]
        self.usage = _Usage(i, o)


class _Messages:
    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self.calls = 0
        self.received: list[list[dict]] = []

    async def create(self, **kwargs):  # noqa: ANN003
        self.received.append(kwargs["messages"])
        reply = self._replies[self.calls]
        self.calls += 1
        return _Resp(reply)


class FakeClient:
    def __init__(self, replies: list[str]) -> None:
        self.messages = _Messages(replies)


# --- source extraction --------------------------------------------------------------


def test_extract_prefers_fenced_jmodel_block():
    assert extract_jmodel_source("blah\n```jmodel\nvar x >= 0;\n```\ntrailing") == "var x >= 0;"


def test_extract_falls_back_to_whole_text_without_fence():
    assert extract_jmodel_source("  var x >= 0;  ") == "var x >= 0;"


def test_extract_handles_bare_fence():
    assert extract_jmodel_source("```\nvar x >= 0;\n```") == "var x >= 0;"


# --- the loop -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_attempt_compiles():
    client = FakeClient([GOOD])
    out = await generate_jmodel(
        client=client, model="m", max_tokens=1000, description="pick one item", attachments=[]
    )
    assert out.ok is True
    assert out.attempts == 1
    assert out.input_tokens == 100 and out.output_tokens == 50
    assert out.error_message is None
    compile_jmodel(out.source)  # the returned source really compiles


@pytest.mark.asyncio
async def test_retry_feeds_error_back_and_recovers():
    client = FakeClient([BROKEN, GOOD])
    out = await generate_jmodel(
        client=client, model="m", max_tokens=1000, description="pick", attachments=[]
    )
    assert out.ok is True
    assert out.attempts == 2
    # Tokens summed across both attempts.
    assert out.input_tokens == 200 and out.output_tokens == 100
    # The 2nd call carried the conversation: user, assistant(raw), user(retry).
    assert len(client.messages.received[1]) == 3
    assert client.messages.received[1][1]["role"] == "assistant"
    assert "did not compile" in client.messages.received[1][2]["content"]


@pytest.mark.asyncio
async def test_all_attempts_fail_returns_best_effort_and_error():
    client = FakeClient([BROKEN, BROKEN, BROKEN])
    out = await generate_jmodel(
        client=client, model="m", max_tokens=1000, description="x", attachments=[]
    )
    assert out.ok is False
    assert out.attempts == 3
    assert out.error_message  # the last compile error is surfaced
    assert out.source  # the best-effort draft is still returned (editable)


@pytest.mark.asyncio
async def test_max_attempts_respected():
    client = FakeClient([BROKEN, BROKEN, BROKEN, BROKEN])
    out = await generate_jmodel(
        client=client,
        model="m",
        max_tokens=1000,
        description="x",
        attachments=[],
        max_attempts=2,
    )
    assert out.attempts == 2
    assert client.messages.calls == 2


# --- vision block assembly ----------------------------------------------------------


def test_image_attachment_becomes_image_block():
    blocks = _build_first_turn(
        "", [DSLGenerateAttachment(media_type="image/png", data="QUJD")], None
    )
    assert len(blocks) == 2
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"] == {"type": "base64", "media_type": "image/png", "data": "QUJD"}
    # Image-only: the text block carries a default "read the attachment" instruction.
    assert "attached" in blocks[0]["text"].lower()


def test_pdf_attachment_becomes_document_block():
    blocks = _build_first_turn(
        "model this", [DSLGenerateAttachment(media_type="application/pdf", data="QUJD")], None
    )
    assert blocks[1]["type"] == "document"
    assert blocks[1]["source"]["media_type"] == "application/pdf"


def test_current_source_quoted_for_refine():
    blocks = _build_first_turn("add a budget constraint", [], "var x >= 0;\nminimize o: x;")
    assert "Refine this existing JModel draft" in blocks[0]["text"]
    assert "var x >= 0;" in blocks[0]["text"]


def test_unknown_media_type_is_dropped_defensively():
    blocks = _build_first_turn(
        "m", [DSLGenerateAttachment(media_type="image/tiff", data="QUJD")], None
    )
    assert all(b["type"] == "text" for b in blocks)  # no image/document block forwarded


# --- exemplar guard -----------------------------------------------------------------


def test_prompt_exemplars_compile():
    """Every ```jmodel exemplar in the system prompt must compile to a valid problem."""
    blocks = re.findall(r"```jmodel\s*\n(.*?)```", JMODEL_GENERATION_SYSTEM_PROMPT, re.DOTALL)
    assert len(blocks) >= 3, "expected the curated exemplars in the prompt"
    for i, block in enumerate(blocks, 1):
        try:
            problem = compile_jmodel(block.strip())
        except JModelError as exc:  # pragma: no cover - failure detail
            pytest.fail(f"exemplar {i} did not compile: {exc.message} (pos {exc.position})")
        assert problem.variables, f"exemplar {i} produced no variables"
        assert problem.objective is not None
