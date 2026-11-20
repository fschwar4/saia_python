"""Generation responses as SAIA sends them, shared by the tests.

Recorded from the live gateway on 2026-11-20 with
``qwen3-30b-a3b-instruct-2507`` (``temperature=0``, ``max_tokens=4``, prompt
``"Say hi in one word:"``); only the request ids are replaced. The extra vLLM
fields (``kv_transfer_params``, ``token_ids``, …) are kept on purpose, so the
helpers are tested against the real shape rather than a minimal one.
"""

from __future__ import annotations

#: A non-streaming ``/completions`` response.
COMPLETION = {
    "id": "cmpl-test",
    "object": "text_completion",
    "created": 1795197079,
    "model": "qwen3-30b-a3b-instruct-2507",
    "choices": [
        {
            "index": 0,
            "text": " Hello\n\nHello!",
            "logprobs": None,
            "finish_reason": "length",
            "stop_reason": None,
            "token_ids": None,
            "prompt_logprobs": None,
            "prompt_token_ids": None,
            "routed_experts": None,
            "weight_versions": None,
        }
    ],
    "service_tier": None,
    "system_fingerprint": "vllm-0.34.0-0baa6153",
    "usage": {
        "prompt_tokens": 6,
        "total_tokens": 10,
        "completion_tokens": 4,
        "completion_tokens_details": None,
    },
    "kv_transfer_params": None,
    "ec_transfer_params": None,
    "metrics": None,
}

#: The same request streamed: the raw SSE lines, blank separators included.
#: ``data:`` lines only, a final usage chunk with empty ``choices``, then
#: ``[DONE]``.
COMPLETION_STREAM_LINES = [
    'data: {"id":"cmpl-test","object":"text_completion","created":1795197081,"model":"qwen3-30b-a3b-instruct-2507","choices":[{"index":0,"text":" Hello","logprobs":null,"finish_reason":null,"stop_reason":null,"prompt_token_ids":null,"token_ids":null,"weight_versions":null}],"kv_transfer_params":null}',
    "",
    'data: {"id":"cmpl-test","object":"text_completion","created":1795197081,"model":"qwen3-30b-a3b-instruct-2507","choices":[{"index":0,"text":"\\n\\n","logprobs":null,"finish_reason":null,"stop_reason":null,"prompt_token_ids":null,"token_ids":null,"weight_versions":null}],"kv_transfer_params":null}',
    "",
    'data: {"id":"cmpl-test","object":"text_completion","created":1795197081,"model":"qwen3-30b-a3b-instruct-2507","choices":[{"index":0,"text":"Hello","logprobs":null,"finish_reason":null,"stop_reason":null,"prompt_token_ids":null,"token_ids":null,"weight_versions":null}],"kv_transfer_params":null}',
    "",
    'data: {"id":"cmpl-test","object":"text_completion","created":1795197081,"model":"qwen3-30b-a3b-instruct-2507","choices":[{"index":0,"text":"!","logprobs":null,"finish_reason":"length","stop_reason":null,"prompt_token_ids":null,"token_ids":null,"weight_versions":null}],"kv_transfer_params":null}',
    "",
    'data: {"id":"cmpl-test","object":"text_completion","created":1795197081,"model":"qwen3-30b-a3b-instruct-2507","choices":[],"usage":{"prompt_tokens":6,"total_tokens":10,"completion_tokens":4},"system_fingerprint":"vllm-0.34.0-0baa6153"}',
    "",
    "data: [DONE]",
    "",
]

#: The text the stream adds up to (the same as the non-streaming answer).
COMPLETION_TEXT = " Hello\n\nHello!"

#: An invalid parameter (``max_tokens=-1``) is rejected with HTTP 400 before
#: anything is streamed, with this body.
COMPLETION_400_BODY = {
    "error": {
        "message": "max_tokens must be at least 1, got -1. (parameter=max_tokens, value=-1)",
        "type": "BadRequestError",
        "param": "max_tokens",
        "code": 400,
    }
}

#: ``n=2``, streamed: the two choices arrive in alternating chunks (trimmed to
#: the fields that matter). Choice 0 reads ``" 3,"``, choice 1 the same here.
COMPLETION_N2_CHUNKS = [
    {"object": "text_completion", "choices": [{"index": 0, "text": " "}]},
    {"object": "text_completion", "choices": [{"index": 1, "text": " "}]},
    {"object": "text_completion", "choices": [{"index": 0, "text": "3"}]},
    {"object": "text_completion", "choices": [{"index": 1, "text": "3"}]},
    {"object": "text_completion", "choices": [{"index": 0, "text": ","}]},
    {"object": "text_completion", "choices": [{"index": 1, "text": ","}]},
    {
        "object": "text_completion",
        "choices": [],
        "usage": {"prompt_tokens": 8, "total_tokens": 14, "completion_tokens": 6},
    },
]
