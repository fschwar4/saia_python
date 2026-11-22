"""Live check that SAIA's ``/v1/responses`` route still answers.

As of 2026-11-20, GWDG's documentation does not list ``/responses``; the route
works and returns genuine Responses API objects (checked live that day). These
tests track that against the real service: the first with a raw request,
independent of saia-python, the other two through :meth:`ResponsesService.create
<saia_python.responses_api.ResponsesService.create>`, plain and streamed. They
need an API key and the network, are gated behind the ``SAIA_RESPONSES_LIVE``
environment variable and never run in CI or the offline gate by default::

    SAIA_RESPONSES_LIVE=1 pytest tests/test_live_responses_route.py

The native tests check the shape of the answer, how a stream ends and what
:func:`~saia_python.text_of` reads. ``SAIA_RESPONSES_LIVE_MODEL`` overrides the
probed model. Keep it a non-reasoning model: a reasoning model can spend the
small token budget thinking and come back ``incomplete``.
"""

from __future__ import annotations

import os

import pytest
import requests

from saia_python import (
    RateLimitError,
    SAIAClient,
    iter_text,
    load_api_key,
    resolve_base_url,
    text_of,
    usage_of,
)

MODEL = os.environ.get("SAIA_RESPONSES_LIVE_MODEL", "meta-llama-3.1-8b-instruct")
INSTRUCTIONS = "Answer in one word."
QUESTION = "What is the capital of France?"

pytestmark = pytest.mark.skipif(
    not os.environ.get("SAIA_RESPONSES_LIVE"),
    reason="set SAIA_RESPONSES_LIVE=1 to run the network-backed /v1/responses check",
)


def _counted(usage: dict) -> bool:
    """Whether all three token counts came back as positive integers."""
    return all(
        isinstance(usage.get(key), int) and usage[key] > 0
        for key in ("input_tokens", "output_tokens", "total_tokens")
    )


def test_live_responses_route_still_answers():
    resp = requests.post(
        f"{resolve_base_url()}/responses",
        headers={"Authorization": f"Bearer {load_api_key()}"},
        json={
            "model": MODEL,
            "instructions": INSTRUCTIONS,
            "input": QUESTION,
            "max_output_tokens": 16,
        },
        timeout=(10, 60),
    )
    if resp.status_code == 429:
        pytest.skip("rate-limited (HTTP 429); cannot tell whether the route works")
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"

    body = resp.json()
    # Only the Responses API answers in this shape: Chat Completions would say
    # "chat.completion", answer under "choices", and count prompt/completion tokens.
    assert body["object"] == "response"
    assert body["status"] == "completed"
    texts = [
        part["text"]
        for item in body["output"]
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    ]
    assert any(text.strip() for text in texts), body["output"]
    assert {"input_tokens", "output_tokens"} <= body["usage"].keys()


def test_live_responses_create_returns_a_response():
    try:
        result = SAIAClient().responses.create(
            MODEL,
            QUESTION,
            instructions=INSTRUCTIONS,
            max_output_tokens=16,
            retry=False,
        )
    except RateLimitError:
        pytest.skip("rate-limited (HTTP 429); cannot tell whether the route works")
    assert isinstance(result, dict)
    assert result["object"] == "response"
    assert result["status"] == "completed", result.get("incomplete_details")
    assert text_of(result).strip(), result["output"]
    assert _counted(usage_of(result)), result.get("usage")


def test_live_responses_stream_ends_with_response_completed():
    try:
        stream = SAIAClient().responses.create(
            MODEL,
            QUESTION,
            instructions=INSTRUCTIONS,
            max_output_tokens=16,
            stream=True,
            retry=False,
        )
        text = iter_text(stream)
        answer = "".join(text)
    except RateLimitError:
        pytest.skip("rate-limited (HTTP 429); cannot tell whether the route works")
    assert answer.strip()
    # The stream ends with response.completed and no [DONE]. That last event
    # carries the whole response, so text_of reads the same answer from it.
    assert text.last["type"] == "response.completed", text.last
    assert text_of(text.last).strip() == answer.strip()
    assert _counted(text.usage), text.usage
