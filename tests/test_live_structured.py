"""Live check that SAIA still enforces a ``json_schema`` ``response_format``.

Calls :meth:`ChatService.completions_structured` against the real service, so it
needs an API key and the network. It is gated behind the
``SAIA_STRUCTURED_LIVE`` environment variable and never runs in CI or the
offline gate by default::

    SAIA_STRUCTURED_LIVE=1 pytest tests/test_live_structured.py

The prompt never mentions JSON, so a schema-shaped answer shows that the server
enforces the schema, not that the model followed instructions.
``SAIA_STRUCTURED_LIVE_MODEL`` overrides the model. No ``max_tokens`` is set, so
a reasoning model has room to think before it answers.
"""

from __future__ import annotations

import os
from typing import Literal

import pytest
from pydantic import BaseModel

from saia_python import RateLimitError, SAIAClient

MODEL = os.environ.get("SAIA_STRUCTURED_LIVE_MODEL", "meta-llama-3.1-8b-instruct")


class Sentiment(BaseModel):
    label: Literal["positive", "negative", "neutral"]
    confidence: float


@pytest.mark.skipif(
    not os.environ.get("SAIA_STRUCTURED_LIVE"),
    reason="set SAIA_STRUCTURED_LIVE=1 to run the network-backed structured-output check",
)
def test_live_completions_structured_returns_a_validated_model():
    try:
        result = SAIAClient().chat.completions_structured(
            MODEL,
            [{"role": "user", "content": "Sentiment of: 'The update broke my build.'"}],
            Sentiment,
            retry=False,
        )
    except RateLimitError:
        pytest.skip("rate-limited (HTTP 429); cannot tell whether the schema holds")
    # completions_structured raises StructuredOutputError on anything unusable,
    # so reaching this line means the answer validated.
    assert isinstance(result, Sentiment)
