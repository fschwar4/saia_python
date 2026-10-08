"""Live check that SAIA's undocumented ``/v1/responses`` route still answers.

GWDG's docs say SAIA does not provide OpenAI's Responses API, yet the route
currently returns genuine Responses API objects. This test tracks that against
the real service, so it needs an API key and the network. It is gated behind the
``SAIA_RESPONSES_LIVE`` environment variable and never runs in CI or the offline
gate by default::

    SAIA_RESPONSES_LIVE=1 pytest tests/test_live_responses_route.py

``SAIA_RESPONSES_LIVE_MODEL`` overrides the probed model. Keep it a
non-reasoning model: a reasoning model can spend the small token budget thinking
and come back ``incomplete``.
"""

from __future__ import annotations

import os

import pytest
import requests

from saia_python import load_api_key, resolve_base_url

MODEL = os.environ.get("SAIA_RESPONSES_LIVE_MODEL", "meta-llama-3.1-8b-instruct")


@pytest.mark.skipif(
    not os.environ.get("SAIA_RESPONSES_LIVE"),
    reason="set SAIA_RESPONSES_LIVE=1 to run the network-backed /v1/responses check",
)
def test_live_responses_route_still_answers():
    resp = requests.post(
        f"{resolve_base_url()}/responses",
        headers={"Authorization": f"Bearer {load_api_key()}"},
        json={
            "model": MODEL,
            "instructions": "Answer in one word.",
            "input": "What is the capital of France?",
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
