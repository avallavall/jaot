"""Tests for how reasoning is requested from Anthropic (app.services.llm.thinking).

The two failure modes this guards against are both silent at code-review time
and fatal at runtime:

- Manual extended thinking (``{"type": "enabled", "budget_tokens": N}``) is
  rejected with a 400 by every model from Opus 4.7 / Sonnet 5 onwards, so a
  stray ``budget_tokens`` anywhere breaks the whole assistant.
- Omitting ``thinking`` no longer means "do not think" from Sonnet 5 onwards.
  Since ``max_tokens`` caps reasoning and answer together, an unset parameter
  quietly eats the output budget and truncates the JSON.

Every call site is therefore covered end-to-end: whatever the service layer
does, the dict that reaches the Anthropic client must carry an explicit,
valid thinking configuration.
"""

import json

import pytest

from app.services.llm.thinking import (
    DEFAULT_EFFORT,
    VALID_EFFORT_LEVELS,
    apply_thinking,
    resolve_effort,
)
from app.services.platform_settings_service import PlatformSettingsService as PSS

MINIMAL_FORMULATION = {
    "problem_name": "Tiny",
    "summary": "A single-variable problem used to exercise the request path.",
    "variables": [
        {
            "name": "x",
            "type": "integer",
            "lower_bound": 0,
            "upper_bound": 10,
            "description": "Units produced",
        }
    ],
    "constraints": [{"name": "cap", "expression": "x <= 5", "description": "Capacity limit"}],
    "objective": {
        "sense": "maximize",
        "expression": "2 * x",
        "description": "Maximize output",
    },
}

GEN_GOOD_JMODEL = "```jmodel\nvar x binary;\nmaximize obj: x;\n```"


class _Delta:
    def __init__(self, text=None, stop_reason=None):
        if text is not None:
            self.text = text
        if stop_reason is not None:
            self.stop_reason = stop_reason
        self.type = "text_delta"


class _Event:
    def __init__(self, type_, delta):
        self.type = type_
        self.delta = delta


class _CapturingStream:
    """Async context manager standing in for ``client.messages.stream()``."""

    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for event in self.events:
            yield event


class _CapturingMessages:
    """Records the kwargs of every request, for both stream and create."""

    def __init__(self, reply_text):
        self.reply_text = reply_text
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return _CapturingStream(
            [
                _Event("content_block_delta", _Delta(text=self.reply_text)),
                _Event("message_delta", _Delta(stop_reason="end_turn")),
            ]
        )

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.reply_text)


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    input_tokens = 10
    output_tokens = 5


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


class _CapturingClient:
    def __init__(self, reply_text):
        self.messages = _CapturingMessages(reply_text)


def _thinking_of(client) -> dict:
    """The thinking block of the single request the client received."""
    assert len(client.messages.calls) >= 1, "no request reached the Anthropic client"
    return client.messages.calls[0]["thinking"]


# --------------------------------------------------------------------------- #
# resolve_effort
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_resolve_effort_reads_the_setting(db_session):
    PSS.set(db_session, "LLM_THINKING_EFFORT", "max")
    db_session.flush()
    assert resolve_effort(db_session) == "max"


@pytest.mark.integration
def test_resolve_effort_normalises_case_and_whitespace(db_session):
    PSS.set(db_session, "LLM_THINKING_EFFORT", "  MEDIUM  ")
    db_session.flush()
    assert resolve_effort(db_session) == "medium"


# CONTRACT-TEST: an unrecognised effort value degrades to the API default instead
# of reaching Anthropic and turning every advanced request into a 400.
@pytest.mark.integration
@pytest.mark.parametrize("bad", ["", "turbo", "9000", "hight"])
def test_resolve_effort_falls_back_on_invalid_value(db_session, bad):
    PSS.set(db_session, "LLM_THINKING_EFFORT", bad)
    db_session.flush()
    assert resolve_effort(db_session) == DEFAULT_EFFORT
    assert DEFAULT_EFFORT in VALID_EFFORT_LEVELS


# --------------------------------------------------------------------------- #
# apply_thinking
# --------------------------------------------------------------------------- #


def test_apply_thinking_disabled_is_explicit():
    """Off must be stated, not implied by omission."""
    kwargs: dict = {}
    apply_thinking(kwargs, thinking=False)
    assert kwargs["thinking"] == {"type": "disabled"}


def test_apply_thinking_disabled_does_not_touch_the_db_or_output_config():
    # db=None and no session opened: disabling needs no settings lookup.
    kwargs: dict = {}
    apply_thinking(kwargs, thinking=False, db=None)
    assert "output_config" not in kwargs


@pytest.mark.integration
def test_apply_thinking_enabled_uses_adaptive_and_effort(db_session):
    PSS.set(db_session, "LLM_THINKING_EFFORT", "xhigh")
    db_session.flush()

    kwargs: dict = {}
    apply_thinking(kwargs, thinking=True, db=db_session)

    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["effort"] == "xhigh"


# CONTRACT-TEST: effort is merged into output_config, never assigned over it —
# dropping the structured-output format would turn the reply into free text and
# break every downstream json.loads.
@pytest.mark.integration
def test_apply_thinking_preserves_structured_output_format(db_session):
    fmt = {"type": "json_schema", "schema": {"type": "object"}}
    kwargs: dict = {"output_config": {"format": fmt}}

    apply_thinking(kwargs, thinking=True, db=db_session)

    assert kwargs["output_config"]["format"] == fmt
    assert kwargs["output_config"]["effort"] in VALID_EFFORT_LEVELS


# CONTRACT-TEST: manual extended thinking is a 400 on every current model. No
# code path may emit budget_tokens or type=enabled again.
@pytest.mark.integration
@pytest.mark.parametrize("thinking", [True, False])
def test_apply_thinking_never_emits_manual_extended_thinking(db_session, thinking):
    kwargs: dict = {}
    apply_thinking(kwargs, thinking=thinking, db=db_session)

    serialized = json.dumps(kwargs)
    assert "budget_tokens" not in serialized
    assert kwargs["thinking"]["type"] in ("adaptive", "disabled")


# --------------------------------------------------------------------------- #
# Call sites — what actually reaches the Anthropic client
# --------------------------------------------------------------------------- #


# CONTRACT-TEST: the advanced path streams with adaptive thinking.
@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_formulation_advanced_sends_adaptive(db_session):
    from app.services.llm.formulation_service import generate_formulation

    client = _CapturingClient(json.dumps(MINIMAL_FORMULATION))
    async for _ in generate_formulation(
        [{"role": "user", "content": "maximise output"}],
        "claude-opus-5",
        thinking=True,
        db=db_session,
        client=client,
    ):
        pass

    assert _thinking_of(client) == {"type": "adaptive"}
    assert client.messages.calls[0]["output_config"]["effort"] in VALID_EFFORT_LEVELS
    # The JSON schema must survive alongside the effort hint.
    assert "format" in client.messages.calls[0]["output_config"]


# CONTRACT-TEST: the default path disables thinking explicitly, so the output
# budget is spent on the formulation rather than on reasoning.
@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_formulation_default_disables_thinking(db_session):
    from app.services.llm.formulation_service import generate_formulation

    client = _CapturingClient(json.dumps(MINIMAL_FORMULATION))
    async for _ in generate_formulation(
        [{"role": "user", "content": "maximise output"}],
        "claude-sonnet-5",
        thinking=False,
        db=db_session,
        client=client,
    ):
        pass

    assert _thinking_of(client) == {"type": "disabled"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_text_response_sends_explicit_thinking(db_session):
    from app.services.llm.formulation_service import generate_text_response

    for thinking, expected in ((True, "adaptive"), (False, "disabled")):
        client = _CapturingClient("a plain text explanation")
        async for _ in generate_text_response(
            [{"role": "user", "content": "why is this infeasible?"}],
            "claude-opus-5",
            thinking=thinking,
            db=db_session,
            client=client,
        ):
            pass

        assert _thinking_of(client)["type"] == expected


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunked_generation_sends_explicit_thinking(db_session):
    """The chunked fallback used to hardcode budget_tokens=2048."""
    from app.schemas.llm import VARIABLES_CHUNK_SCHEMA
    from app.services.llm.chunked_generation import _generate_chunk

    for thinking, expected in ((True, "adaptive"), (False, "disabled")):
        client = _CapturingClient(json.dumps(MINIMAL_FORMULATION))
        await _generate_chunk(
            [{"role": "user", "content": "maximise output"}],
            "claude-opus-5",
            VARIABLES_CHUNK_SCHEMA,
            "system prompt",
            thinking=thinking,
            db=db_session,
            client=client,
        )

        assert _thinking_of(client)["type"] == expected


# CONTRACT-TEST: JModel generation leans on the compile-retry loop, not on
# reasoning, and its output budget is deliberately small — thinking stays off.
@pytest.mark.integration
@pytest.mark.asyncio
async def test_jmodel_generate_disables_thinking():
    from app.services.jmodel_generate import generate_jmodel

    client = _CapturingClient(GEN_GOOD_JMODEL)
    outcome = await generate_jmodel(
        client=client,
        model="claude-sonnet-5",
        max_tokens=4096,
        description="pick an item",
        attachments=[],
    )

    assert outcome.ok is True
    assert _thinking_of(client) == {"type": "disabled"}
