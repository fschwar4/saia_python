"""Tests for the pure request builders in :mod:`saia_python._payloads`.

Transport-free, so these run with no client at all. They pin the ARCANA
injection that the sync services, the async services, and external gateways
all share.
"""

from __future__ import annotations

from saia_python import (
    INFERENCE_SERVICE,
    apply_arcana_fields,
    arcana_chat_headers,
    build_chat_body,
    build_completion_body,
    build_message_body,
    build_response_body,
)


def test_build_chat_body_minimal_omits_none_knobs():
    body = build_chat_body("m", [{"role": "user", "content": "hi"}])
    assert body == {"model": "m", "messages": [{"role": "user", "content": "hi"}]}


def test_build_chat_body_includes_set_knobs_and_merges_kwargs():
    body = build_chat_body(
        "m", [], temperature=0.2, top_p=0.9, max_tokens=64, stream=True, stop=["x"]
    )
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.9
    assert body["max_tokens"] == 64
    assert body["stream"] is True
    assert body["stop"] == ["x"]


def test_build_completion_body_minimal_omits_none_knobs():
    assert build_completion_body("m", "Once upon a time") == {
        "model": "m",
        "prompt": "Once upon a time",
    }


def test_build_completion_body_includes_set_knobs_and_merges_kwargs():
    body = build_completion_body(
        "m", "x", max_tokens=8, temperature=0, top_p=0.5, stop=["\n"], echo=True
    )
    assert body == {
        "model": "m",
        "prompt": "x",
        "max_tokens": 8,
        "temperature": 0,  # 0 is a value, not "unset"
        "top_p": 0.5,
        "stop": ["\n"],
        "echo": True,
    }


def test_build_completion_body_passes_a_prompt_list_through():
    body = build_completion_body("m", ["a", "b"])
    assert body["prompt"] == ["a", "b"]


def test_build_response_body_minimal_omits_none_knobs():
    assert build_response_body("m", "Hi") == {"model": "m", "input": "Hi"}


def test_build_response_body_includes_set_knobs_and_merges_kwargs():
    tools = [{"type": "function", "name": "get_weather", "parameters": {}}]
    body = build_response_body(
        "m",
        [{"role": "user", "content": "Hi"}],
        instructions="Be brief.",
        max_output_tokens=64,
        temperature=0,
        top_p=0.9,
        tools=tools,
        text={"format": {"type": "text"}},
    )
    assert body == {
        "model": "m",
        "input": [{"role": "user", "content": "Hi"}],
        "instructions": "Be brief.",
        "max_output_tokens": 64,
        "temperature": 0,
        "top_p": 0.9,
        "tools": tools,
        "text": {"format": {"type": "text"}},
    }


def test_build_message_body_minimal_sends_max_tokens_and_omits_none_knobs():
    messages = [{"role": "user", "content": "Hi"}]
    assert build_message_body("m", messages, 64) == {
        "model": "m",
        "messages": messages,
        "max_tokens": 64,
    }


def test_build_message_body_includes_set_knobs_and_merges_kwargs():
    tools = [{"name": "get_weather", "input_schema": {"type": "object"}}]
    body = build_message_body(
        "m",
        [{"role": "user", "content": "Hi"}],
        128,
        system="Be brief.",
        temperature=0,
        top_p=0.9,
        tools=tools,
        tool_choice={"type": "tool", "name": "get_weather"},
        stop_sequences=["END"],
    )
    assert body == {
        "model": "m",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 128,
        "system": "Be brief.",
        "temperature": 0,
        "top_p": 0.9,
        "tools": tools,
        "tool_choice": {"type": "tool", "name": "get_weather"},
        "stop_sequences": ["END"],
    }


def test_build_message_body_passes_system_blocks_through():
    system = [{"type": "text", "text": "Be brief."}]
    assert build_message_body("m", [], 8, system=system)["system"] is system


def test_apply_arcana_fields_returns_new_dict_and_leaves_input_unmutated():
    original = {"model": "m", "messages": []}
    out = apply_arcana_fields(original, "owner/kb")
    assert out["enable-tools"] is True
    assert out["arcana"] == {"id": "owner/kb"}
    assert "enable-tools" not in original  # input untouched
    assert out is not original


def test_apply_arcana_fields_wins_over_preexisting_keys():
    # A stray enable-tools=False in the body must not disable retrieval.
    out = apply_arcana_fields(
        {"enable-tools": False, "arcana": {"id": "old"}}, "new/kb"
    )
    assert out["enable-tools"] is True
    assert out["arcana"] == {"id": "new/kb"}


def test_arcana_chat_headers_carry_auth_and_gateway():
    headers = arcana_chat_headers("KEY")
    assert headers["Authorization"] == "Bearer KEY"
    assert headers["Accept"] == "application/json"
    assert headers["inference-service"] == INFERENCE_SERVICE == "saia-openai-gateway"


def test_arcana_chat_headers_merge_extra_last():
    headers = arcana_chat_headers("KEY", extra={"X-Request-ID": "rid"})
    assert headers["X-Request-ID"] == "rid"
    assert headers["inference-service"] == "saia-openai-gateway"
