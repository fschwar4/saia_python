"""Live check that SAIA's ``/v1/completions`` route still answers as expected.

Calls :meth:`CompletionsService.create
<saia_python.completions.CompletionsService.create>` against the real service,
plain and streamed, so it needs an API key and the network. It is gated behind
the ``SAIA_COMPLETIONS_LIVE`` environment variable and never runs in CI or the
offline gate by default::

    SAIA_COMPLETIONS_LIVE=1 pytest tests/test_live_completions_route.py

Each test checks the shape of the answer, how a stream ends and what
:func:`~saia_python.text_of` reads. ``SAIA_COMPLETIONS_LIVE_MODEL`` overrides
the model.
"""

from __future__ import annotations

import os

import pytest

from saia_python import RateLimitError, SAIAClient, iter_text, text_of, usage_of

MODEL = os.environ.get("SAIA_COMPLETIONS_LIVE_MODEL", "meta-llama-3.1-8b-instruct")
PROMPT = "The capital of France is"

pytestmark = pytest.mark.skipif(
    not os.environ.get("SAIA_COMPLETIONS_LIVE"),
    reason="set SAIA_COMPLETIONS_LIVE=1 to run the network-backed /v1/completions check",
)


def _counted(usage: dict) -> bool:
    """Whether all three token counts came back as positive integers."""
    return all(
        isinstance(usage.get(key), int) and usage[key] > 0
        for key in ("input_tokens", "output_tokens", "total_tokens")
    )


def test_live_completion_is_a_text_completion():
    try:
        result = SAIAClient().completions.create(
            MODEL, PROMPT, max_tokens=8, temperature=0, retry=False
        )
    except RateLimitError:
        pytest.skip("rate-limited (HTTP 429); cannot tell whether the route works")
    assert isinstance(result, dict)
    assert result["object"] == "text_completion"
    assert text_of(result).strip(), result["choices"]
    assert _counted(usage_of(result)), result.get("usage")


def test_live_completion_stream_ends_with_a_usage_chunk():
    try:
        stream = SAIAClient().completions.create(
            MODEL, PROMPT, max_tokens=8, temperature=0, stream=True, retry=False
        )
        text = iter_text(stream)
        pieces = list(text)
    except RateLimitError:
        pytest.skip("rate-limited (HTTP 429); cannot tell whether the route works")
    assert "".join(pieces).strip()
    # SAIA ends a completion stream with a chunk whose choices are empty and
    # which carries the token counts, then [DONE] (seen 2026-11-20).
    assert text.last["choices"] == [], text.last
    assert _counted(text.usage), text.last
