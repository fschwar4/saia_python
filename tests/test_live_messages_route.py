"""Live check that SAIA's ``/v1/messages`` route still answers in Anthropic's format.

As of 2026-11-22, GWDG's documentation does not list ``/messages``; the route
works and answers in Anthropic's Messages format (checked live that day). This
test tracks that against the real service through :meth:`MessagesService.create
<saia_python.messages.MessagesService.create>`, plain and streamed, so it needs
an API key and the network. It is gated behind the ``SAIA_MESSAGES_LIVE``
environment variable and never runs in CI or the offline gate by default::

    SAIA_MESSAGES_LIVE=1 pytest tests/test_live_messages_route.py

Each test checks the shape of the answer, how a stream ends and what
:func:`~saia_python.text_of` reads. ``SAIA_MESSAGES_LIVE_MODEL`` overrides the
model. Keep it a non-reasoning model: a reasoning model can spend the small
token budget thinking and stop before it answers.
"""

from __future__ import annotations

import os

import pytest

from saia_python import RateLimitError, SAIAClient, iter_text, text_of, usage_of

MODEL = os.environ.get("SAIA_MESSAGES_LIVE_MODEL", "meta-llama-3.1-8b-instruct")
MESSAGES = [{"role": "user", "content": "What is the capital of France?"}]
# A system prompt also keeps meta-llama-3.1-8b-instruct from getting SAIA's
# default tool-calling prompt, which its template adds when there is none
# (seen 2026-11-22).
SYSTEM = "Answer in one word."

pytestmark = pytest.mark.skipif(
    not os.environ.get("SAIA_MESSAGES_LIVE"),
    reason="set SAIA_MESSAGES_LIVE=1 to run the network-backed /v1/messages check",
)


def _counted(usage: dict) -> bool:
    """Whether all three token counts came back as positive integers."""
    return all(
        isinstance(usage.get(key), int) and usage[key] > 0
        for key in ("input_tokens", "output_tokens", "total_tokens")
    )


def test_live_message_is_an_anthropic_message():
    try:
        result = SAIAClient().messages.create(
            MODEL, MESSAGES, 16, system=SYSTEM, temperature=0, retry=False
        )
    except RateLimitError:
        pytest.skip("rate-limited (HTTP 429); cannot tell whether the route works")
    assert isinstance(result, dict)
    # Only the Messages API answers in this shape: Chat Completions would say
    # "chat.completion" and answer under "choices".
    assert result["type"] == "message"
    assert result["role"] == "assistant"
    assert result["stop_reason"] in {"end_turn", "max_tokens"}, result["stop_reason"]
    assert text_of(result).strip(), result["content"]
    assert _counted(usage_of(result)), result.get("usage")


def test_live_message_stream_ends_with_message_stop():
    try:
        stream = SAIAClient().messages.create(
            MODEL,
            MESSAGES,
            16,
            system=SYSTEM,
            temperature=0,
            stream=True,
            retry=False,
        )
        text = iter_text(stream)
        pieces = list(text)
    except RateLimitError:
        pytest.skip("rate-limited (HTTP 429); cannot tell whether the route works")
    assert "".join(pieces).strip()
    # The stream ends with message_stop and no [DONE]. The input tokens come
    # in message_start and the final counts in message_delta (seen 2026-11-22),
    # which text.usage merges.
    assert text.last["type"] == "message_stop", text.last
    assert _counted(text.usage), text.usage
