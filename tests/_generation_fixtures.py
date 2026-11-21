"""Generation responses as SAIA sends them, shared by the tests.

Recorded from the live gateway on 2026-11-20; only the request ids are
replaced. The extra vLLM fields (``kv_transfer_params``, ``token_ids``, …) are
kept on purpose, so the helpers are tested against the real shape rather than
a minimal one; the few trimmed fixtures say so.
"""

from __future__ import annotations

# --- /completions ----------------------------------------------------------------

#: A non-streaming ``/completions`` response (``qwen3-30b-a3b-instruct-2507``,
#: ``temperature=0``, ``max_tokens=4``, prompt ``"Say hi in one word:"``).
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


# --- /responses ------------------------------------------------------------------

#: A non-streaming ``/responses`` response (``qwen3-30b-a3b-instruct-2507``,
#: ``instructions="Answer briefly."``, input ``"Name the three primary colours of
#: light, comma-separated."``, ``max_output_tokens=16``, ``temperature=0``).
RESPONSE = {
    "id": "resp_test",
    "created_at": 1795198600,
    "incomplete_details": None,
    "instructions": "Answer briefly.",
    "metadata": None,
    "model": "qwen3-30b-a3b-instruct-2507",
    "object": "response",
    "output": [
        {
            "id": "msg_test",
            "content": [
                {
                    "annotations": [],
                    "text": "Red, Green, Blue",
                    "type": "output_text",
                    "logprobs": None,
                }
            ],
            "role": "assistant",
            "status": "completed",
            "type": "message",
            "phase": None,
        }
    ],
    "parallel_tool_calls": True,
    "temperature": 0.0,
    "tool_choice": "none",
    "tools": [],
    "top_p": 1.0,
    "background": False,
    "max_output_tokens": 16,
    "max_tool_calls": None,
    "previous_response_id": None,
    "prompt": None,
    "prompt_cache_options": None,
    "prompt_cache_key": None,
    "prompt_cache_retention": None,
    "reasoning": None,
    "safety_identifier": None,
    "service_tier": "auto",
    "status": "completed",
    "text": None,
    "top_logprobs": None,
    "truncation": "disabled",
    "usage": {
        "input_tokens": 27,
        "input_tokens_details": {
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "input_tokens_per_turn": [],
            "cached_tokens_per_turn": [],
        },
        "output_tokens": 6,
        "output_tokens_details": {
            "reasoning_tokens": 0,
            "tool_output_tokens": 0,
            "output_tokens_per_turn": [],
            "tool_output_tokens_per_turn": [],
        },
        "total_tokens": 33,
    },
    "user": None,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
    "kv_transfer_params": None,
    "ec_transfer_params": None,
    "input_messages": None,
    "output_messages": None,
}

#: The same request streamed: ``event:`` and ``data:`` lines, every JSON with its
#: own ``type``, and no ``[DONE]``. ``response.completed`` carries the full
#: response, ``usage`` included.
RESPONSE_STREAM_LINES = [
    "event: response.created",
    'data: {"response":{"id":"resp_test","created_at":1795198602,"incomplete_details":null,"instructions":"Answer briefly.","metadata":null,"model":"qwen3-30b-a3b-instruct-2507","object":"response","output":[],"parallel_tool_calls":true,"temperature":0.0,"tool_choice":"none","tools":[],"top_p":1.0,"background":false,"max_output_tokens":16,"max_tool_calls":null,"previous_response_id":null,"prompt":null,"prompt_cache_options":null,"prompt_cache_key":null,"prompt_cache_retention":null,"reasoning":null,"safety_identifier":null,"service_tier":"auto","status":"in_progress","text":null,"top_logprobs":null,"truncation":"disabled","usage":null,"user":null,"presence_penalty":0.0,"frequency_penalty":0.0,"kv_transfer_params":null,"ec_transfer_params":null,"input_messages":null,"output_messages":null},"sequence_number":0,"type":"response.created"}',
    "",
    "event: response.in_progress",
    'data: {"response":{"id":"resp_test","created_at":1795198602,"incomplete_details":null,"instructions":"Answer briefly.","metadata":null,"model":"qwen3-30b-a3b-instruct-2507","object":"response","output":[],"parallel_tool_calls":true,"temperature":0.0,"tool_choice":"none","tools":[],"top_p":1.0,"background":false,"max_output_tokens":16,"max_tool_calls":null,"previous_response_id":null,"prompt":null,"prompt_cache_options":null,"prompt_cache_key":null,"prompt_cache_retention":null,"reasoning":null,"safety_identifier":null,"service_tier":"auto","status":"in_progress","text":null,"top_logprobs":null,"truncation":"disabled","usage":null,"user":null,"presence_penalty":0.0,"frequency_penalty":0.0,"kv_transfer_params":null,"ec_transfer_params":null,"input_messages":null,"output_messages":null},"sequence_number":1,"type":"response.in_progress"}',
    "",
    "event: response.output_item.added",
    'data: {"item":{"id":"msg_test","content":[],"role":"assistant","status":"in_progress","type":"message","phase":null},"output_index":0,"sequence_number":2,"type":"response.output_item.added"}',
    "",
    "event: response.content_part.added",
    'data: {"content_index":0,"item_id":"msg_test","output_index":0,"part":{"annotations":[],"text":"","type":"output_text","logprobs":[]},"sequence_number":3,"type":"response.content_part.added"}',
    "",
    "event: response.output_text.delta",
    'data: {"content_index":0,"delta":"Red","item_id":"msg_test","logprobs":[],"output_index":0,"sequence_number":4,"type":"response.output_text.delta"}',
    "",
    "event: response.output_text.delta",
    'data: {"content_index":0,"delta":", Green,","item_id":"msg_test","logprobs":[],"output_index":0,"sequence_number":5,"type":"response.output_text.delta"}',
    "",
    "event: response.output_text.delta",
    'data: {"content_index":0,"delta":" Blue","item_id":"msg_test","logprobs":[],"output_index":0,"sequence_number":6,"type":"response.output_text.delta"}',
    "",
    "event: response.output_text.done",
    'data: {"content_index":0,"item_id":"msg_test","logprobs":[],"output_index":0,"sequence_number":7,"text":"Red, Green, Blue","type":"response.output_text.done"}',
    "",
    "event: response.content_part.done",
    'data: {"content_index":0,"item_id":"msg_test","output_index":0,"part":{"annotations":[],"text":"Red, Green, Blue","type":"output_text","logprobs":null},"sequence_number":8,"type":"response.content_part.done"}',
    "",
    "event: response.output_item.done",
    'data: {"item":{"id":"msg_test","content":[{"annotations":[],"text":"Red, Green, Blue","type":"output_text","logprobs":null}],"role":"assistant","status":"completed","type":"message","phase":null},"output_index":0,"sequence_number":9,"type":"response.output_item.done"}',
    "",
    "event: response.completed",
    'data: {"response":{"id":"resp_test","created_at":1795198602,"incomplete_details":null,"instructions":"Answer briefly.","metadata":null,"model":"qwen3-30b-a3b-instruct-2507","object":"response","output":[{"id":"msg_test","content":[{"annotations":[],"text":"Red, Green, Blue","type":"output_text","logprobs":null}],"role":"assistant","status":"completed","type":"message","phase":null}],"parallel_tool_calls":true,"temperature":0.0,"tool_choice":"none","tools":[],"top_p":1.0,"background":false,"max_output_tokens":16,"max_tool_calls":null,"previous_response_id":null,"prompt":null,"prompt_cache_options":null,"prompt_cache_key":null,"prompt_cache_retention":null,"reasoning":null,"safety_identifier":null,"service_tier":"auto","status":"completed","text":null,"top_logprobs":null,"truncation":"disabled","usage":{"input_tokens":27,"input_tokens_details":{"cached_tokens":0,"cache_write_tokens":0,"input_tokens_per_turn":[],"cached_tokens_per_turn":[]},"output_tokens":6,"output_tokens_details":{"reasoning_tokens":0,"tool_output_tokens":0,"output_tokens_per_turn":[],"tool_output_tokens_per_turn":[]},"total_tokens":33},"user":null,"presence_penalty":0.0,"frequency_penalty":0.0,"kv_transfer_params":null,"ec_transfer_params":null,"input_messages":null,"output_messages":null},"sequence_number":10,"type":"response.completed"}',
    "",
]

#: The text both add up to.
RESPONSE_TEXT = "Red, Green, Blue"

#: A reasoning model (``deepseek-v4.1-flash-1017``, input ``"What is 2+2? Answer
#: with the number only."``, ``max_output_tokens=512``, ``temperature=0``): a
#: ``reasoning`` item before the message. Trimmed to the fields the helpers read.
RESPONSE_REASONING = {
    "id": "resp_test",
    "object": "response",
    "created_at": 1795198480,
    "model": "deepseek-v4.1-flash-1017",
    "status": "completed",
    "incomplete_details": None,
    "output": [
        {
            "id": "rs_test",
            "summary": [],
            "type": "reasoning",
            "content": [
                {
                    "text": "We need answer only number. 2+2=4. Must comply.",
                    "type": "reasoning_text",
                }
            ],
            "encrypted_content": None,
            "status": None,
        },
        {
            "id": "msg_test",
            "content": [
                {
                    "annotations": [],
                    "text": "4",
                    "type": "output_text",
                    "logprobs": None,
                }
            ],
            "role": "assistant",
            "status": "completed",
            "type": "message",
            "phase": None,
        },
    ],
    "usage": {
        "input_tokens": 43,
        "input_tokens_details": {
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "input_tokens_per_turn": [],
            "cached_tokens_per_turn": [],
        },
        "output_tokens": 19,
        "output_tokens_details": {
            "reasoning_tokens": 16,
            "tool_output_tokens": 0,
            "output_tokens_per_turn": [],
            "tool_output_tokens_per_turn": [],
        },
        "total_tokens": 62,
    },
}

#: The same request streamed: ``response.reasoning_text.delta`` events first,
#: then the answer's ``response.output_text.delta``.
RESPONSE_REASONING_STREAM_LINES = [
    "event: response.created",
    'data: {"response":{"id":"resp_test","created_at":1795198482,"incomplete_details":null,"instructions":null,"metadata":null,"model":"deepseek-v4.1-flash-1017","object":"response","output":[],"parallel_tool_calls":true,"temperature":0.0,"tool_choice":"none","tools":[],"top_p":1.0,"background":false,"max_output_tokens":512,"max_tool_calls":null,"previous_response_id":null,"prompt":null,"reasoning":null,"service_tier":"auto","status":"in_progress","text":null,"top_logprobs":null,"truncation":"disabled","usage":null,"user":null,"presence_penalty":0.0,"frequency_penalty":0.0,"kv_transfer_params":null,"ec_transfer_params":null,"input_messages":null,"output_messages":null},"sequence_number":0,"type":"response.created"}',
    "",
    "event: response.in_progress",
    'data: {"response":{"id":"resp_test","created_at":1795198482,"incomplete_details":null,"instructions":null,"metadata":null,"model":"deepseek-v4.1-flash-1017","object":"response","output":[],"parallel_tool_calls":true,"temperature":0.0,"tool_choice":"none","tools":[],"top_p":1.0,"background":false,"max_output_tokens":512,"max_tool_calls":null,"previous_response_id":null,"prompt":null,"reasoning":null,"service_tier":"auto","status":"in_progress","text":null,"top_logprobs":null,"truncation":"disabled","usage":null,"user":null,"presence_penalty":0.0,"frequency_penalty":0.0,"kv_transfer_params":null,"ec_transfer_params":null,"input_messages":null,"output_messages":null},"sequence_number":1,"type":"response.in_progress"}',
    "",
    "event: response.output_item.added",
    'data: {"item":{"id":"rs_test","summary":[],"type":"reasoning","content":null,"encrypted_content":null,"status":"in_progress"},"output_index":0,"sequence_number":2,"type":"response.output_item.added"}',
    "",
    "event: response.content_part.added",
    'data: {"content_index":0,"item_id":"rs_test","output_index":0,"part":{"text":"","type":"reasoning_text"},"sequence_number":3,"type":"response.content_part.added"}',
    "",
    "event: response.reasoning_text.delta",
    'data: {"content_index":0,"delta":"We","item_id":"rs_test","output_index":0,"sequence_number":4,"type":"response.reasoning_text.delta"}',
    "",
    "event: response.reasoning_text.delta",
    'data: {"content_index":0,"delta":" need answer only number","item_id":"rs_test","output_index":0,"sequence_number":5,"type":"response.reasoning_text.delta"}',
    "",
    "event: response.reasoning_text.delta",
    'data: {"content_index":0,"delta":".","item_id":"rs_test","output_index":0,"sequence_number":6,"type":"response.reasoning_text.delta"}',
    "",
    "event: response.reasoning_text.delta",
    'data: {"content_index":0,"delta":" 2+","item_id":"rs_test","output_index":0,"sequence_number":7,"type":"response.reasoning_text.delta"}',
    "",
    "event: response.reasoning_text.delta",
    'data: {"content_index":0,"delta":"2=4. Must","item_id":"rs_test","output_index":0,"sequence_number":8,"type":"response.reasoning_text.delta"}',
    "",
    "event: response.reasoning_text.delta",
    'data: {"content_index":0,"delta":" comply","item_id":"rs_test","output_index":0,"sequence_number":9,"type":"response.reasoning_text.delta"}',
    "",
    "event: response.reasoning_text.delta",
    'data: {"content_index":0,"delta":".","item_id":"rs_test","output_index":0,"sequence_number":10,"type":"response.reasoning_text.delta"}',
    "",
    "event: response.reasoning_text.done",
    'data: {"content_index":0,"item_id":"rs_test","output_index":0,"sequence_number":11,"text":"We need answer only number. 2+2=4. Must comply.","type":"response.reasoning_text.done"}',
    "",
    "event: response.content_part.done",
    'data: {"content_index":0,"item_id":"rs_test","output_index":0,"part":{"text":"We need answer only number. 2+2=4. Must comply.","type":"reasoning_text"},"sequence_number":12,"type":"response.content_part.done"}',
    "",
    "event: response.output_item.done",
    'data: {"item":{"id":"rs_test","summary":[],"type":"reasoning","content":[{"text":"We need answer only number. 2+2=4. Must comply.","type":"reasoning_text"}],"encrypted_content":null,"status":"completed"},"output_index":0,"sequence_number":13,"type":"response.output_item.done"}',
    "",
    "event: response.output_item.added",
    'data: {"item":{"id":"msg_test","content":[],"role":"assistant","status":"in_progress","type":"message","phase":null},"output_index":1,"sequence_number":14,"type":"response.output_item.added"}',
    "",
    "event: response.content_part.added",
    'data: {"content_index":0,"item_id":"msg_test","output_index":1,"part":{"annotations":[],"text":"","type":"output_text","logprobs":[]},"sequence_number":15,"type":"response.content_part.added"}',
    "",
    "event: response.output_text.delta",
    'data: {"content_index":0,"delta":"4","item_id":"msg_test","logprobs":[],"output_index":1,"sequence_number":16,"type":"response.output_text.delta"}',
    "",
    "event: response.output_text.done",
    'data: {"content_index":0,"item_id":"msg_test","logprobs":[],"output_index":1,"sequence_number":17,"text":"4","type":"response.output_text.done"}',
    "",
    "event: response.content_part.done",
    'data: {"content_index":0,"item_id":"msg_test","output_index":1,"part":{"annotations":[],"text":"4","type":"output_text","logprobs":null},"sequence_number":18,"type":"response.content_part.done"}',
    "",
    "event: response.output_item.done",
    'data: {"item":{"id":"msg_test","content":[{"annotations":[],"text":"4","type":"output_text","logprobs":null}],"role":"assistant","status":"completed","type":"message","phase":null},"output_index":1,"sequence_number":19,"type":"response.output_item.done"}',
    "",
    "event: response.completed",
    'data: {"response":{"id":"resp_test","created_at":1795198482,"incomplete_details":null,"instructions":null,"metadata":null,"model":"deepseek-v4.1-flash-1017","object":"response","output":[{"id":"rs_test","summary":[],"type":"reasoning","content":[{"text":"We need answer only number. 2+2=4. Must comply.","type":"reasoning_text"}],"encrypted_content":null,"status":"completed"},{"id":"msg_test","content":[{"annotations":[],"text":"4","type":"output_text","logprobs":null}],"role":"assistant","status":"completed","type":"message","phase":null}],"parallel_tool_calls":true,"temperature":0.0,"tool_choice":"none","tools":[],"top_p":1.0,"background":false,"max_output_tokens":512,"max_tool_calls":null,"previous_response_id":null,"prompt":null,"reasoning":null,"service_tier":"auto","status":"completed","text":null,"top_logprobs":null,"truncation":"disabled","usage":{"input_tokens":43,"input_tokens_details":{"cached_tokens":0,"cache_write_tokens":0,"input_tokens_per_turn":[],"cached_tokens_per_turn":[]},"output_tokens":19,"output_tokens_details":{"reasoning_tokens":16,"tool_output_tokens":0,"output_tokens_per_turn":[],"tool_output_tokens_per_turn":[]},"total_tokens":62},"user":null,"presence_penalty":0.0,"frequency_penalty":0.0,"kv_transfer_params":null,"ec_transfer_params":null,"input_messages":null,"output_messages":null},"sequence_number":20,"type":"response.completed"}',
    "",
]

#: ``max_output_tokens=4`` ran out: ``status: "incomplete"`` with the partial
#: text. Trimmed to the fields the helpers read.
RESPONSE_INCOMPLETE = {
    "id": "resp_test",
    "object": "response",
    "created_at": 1795198483,
    "model": "qwen3-30b-a3b-instruct-2507",
    "status": "incomplete",
    "incomplete_details": {"reason": "max_output_tokens"},
    "output": [
        {
            "id": "msg_test",
            "content": [
                {
                    "annotations": [],
                    "text": "2, 3",
                    "type": "output_text",
                    "logprobs": None,
                }
            ],
            "role": "assistant",
            "status": "incomplete",
            "type": "message",
            "phase": None,
        }
    ],
    "usage": {
        "input_tokens": 19,
        "input_tokens_details": {
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "input_tokens_per_turn": [],
            "cached_tokens_per_turn": [],
        },
        "output_tokens": 4,
        "output_tokens_details": {
            "reasoning_tokens": 0,
            "tool_output_tokens": 0,
            "output_tokens_per_turn": [],
            "tool_output_tokens_per_turn": [],
        },
        "total_tokens": 23,
    },
}

#: An invalid parameter (``max_output_tokens=-1``) gets HTTP 400 before anything
#: is streamed, with the same body as on ``/completions``.
RESPONSE_400_BODY = COMPLETION_400_BODY
