"""Tests for the pure request builders in :mod:`saia_python._payloads`.

Transport-free, so these run with no client at all. They pin the ARCANA
injection (Rule #6) that the sync services, the async services, and the AVOR
adapter all share.
"""

from __future__ import annotations

from saia_python import (
    INFERENCE_SERVICE,
    apply_arcana_fields,
    arcana_chat_headers,
    build_chat_body,
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
