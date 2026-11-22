"""Tests for ``ChatService.completions`` — the return types, and the object.

Guards the 0.2.0 streaming-parity behaviour: non-streaming attaches a
JSON-serializable ``_rate_limits`` dict, and streaming returns an ``SSEStream``
exposing the same headers via ``.rate_limits``. These first tests use the call
form ``completions(...)``; the ones after them cover ``completions.create(...)``
and the :class:`ChatCompletions` object behind both forms.
"""

import json
from unittest.mock import MagicMock, patch

from saia_python import SAIAClient
from saia_python._http import RetryPolicy
from saia_python._streaming import SSEStream
from saia_python.chat import ChatCompletions, ChatService

from ._rate_limit_headers import CURRENT_OK

_RL_HEADERS = CURRENT_OK


def _make_service() -> ChatService:
    svc = ChatService.__new__(ChatService)
    svc._session = MagicMock()
    svc._base_url = "https://example.com/v1"
    svc._retry = RetryPolicy()
    return svc


def test_completions_non_streaming_attaches_rate_limits_dict():
    """stream=False returns the response dict with a JSON-serializable
    ``_rate_limits`` dict (not a RateLimitInfo instance)."""
    svc = _make_service()
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.headers = _RL_HEADERS
    resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    svc._session.post.return_value = resp

    result = svc.completions("m", [{"role": "user", "content": "hi"}])

    assert isinstance(result, dict)
    assert isinstance(result["_rate_limits"], dict)
    assert result["_rate_limits"]["remaining_10s"] == 9
    # The whole response round-trips through json.dumps — the point of the dict form.
    json.dumps(result)


def test_completions_streaming_returns_sse_stream():
    """stream=True returns an SSEStream whose .rate_limits is ready immediately,
    and POSTs with stream=True."""
    svc = _make_service()
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.headers = _RL_HEADERS
    resp.iter_lines.return_value = iter(["data: [DONE]"])
    svc._session.post.return_value = resp

    result = svc.completions("m", [{"role": "user", "content": "hi"}], stream=True)

    assert isinstance(result, SSEStream)
    assert result.rate_limits["remaining_10s"] == 9
    assert svc._session.post.call_args.kwargs.get("stream") is True


# --- completions.create(...) and the ChatCompletions object -------------------

_BASE = "https://example.com/v1"
_MESSAGES = [{"role": "user", "content": "hi"}]


def _ok_response():
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.headers = _RL_HEADERS
    resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    return resp


def test_create_and_the_call_form_send_the_same_request():
    svc = _make_service()
    svc._session.post.return_value = _ok_response()

    result = svc.completions.create("m", _MESSAGES, temperature=0.2, seed=7)
    svc.completions("m", _MESSAGES, temperature=0.2, seed=7)

    assert result["_rate_limits"]["remaining_10s"] == 9
    first, second = svc._session.post.call_args_list
    assert first == second
    assert first.args == (f"{_BASE}/chat/completions",)
    assert first.kwargs["json"] == {
        "model": "m",
        "messages": _MESSAGES,
        "seed": 7,
        "temperature": 0.2,
    }


def test_completions_is_one_object_per_service():
    svc = _make_service()
    completions = svc.completions
    assert isinstance(completions, ChatCompletions)
    assert svc.completions is completions  # built on first access, then kept
    assert _make_service().completions is not completions
    assert repr(completions) == f"ChatCompletions(base_url={_BASE!r})"


def test_completions_reads_the_service_on_every_call():
    # The object keeps only its service, so nothing it uses can go stale.
    svc = _make_service()
    completions = svc.completions
    svc._session = MagicMock()
    svc._session.post.return_value = _ok_response()
    svc._base_url = "https://other.example/v1"

    completions.create("m", _MESSAGES)

    assert svc._session.post.call_args.args == (
        "https://other.example/v1/chat/completions",
    )


def test_client_chat_completions_belongs_to_its_chat_service():
    client = SAIAClient(api_key="k", base_url=_BASE)
    completions = client.chat.completions
    assert isinstance(completions, ChatCompletions)
    assert completions._service is client.chat
    assert client.chat.completions is completions


def test_patching_completions_on_the_instance_replaces_both_forms():
    svc = _make_service()
    original = svc.completions
    with patch.object(svc, "completions") as mock:
        mock.return_value = "call form"
        mock.create.return_value = "create"
        assert svc.completions("m", _MESSAGES) == "call form"
        assert svc.completions.create("m", _MESSAGES) == "create"
    assert svc.completions is original  # restored after the patch
    svc._session.post.assert_not_called()


def test_patching_create_catches_both_forms():
    svc = _make_service()
    with patch.object(svc.completions, "create", return_value="mocked") as create:
        assert svc.completions.create("m", _MESSAGES) == "mocked"
        assert svc.completions("m", _MESSAGES, max_tokens=5) == "mocked"
    assert create.call_args_list[1].kwargs == {"max_tokens": 5}
    svc._session.post.assert_not_called()


def test_patching_create_on_the_class_catches_every_service():
    first, second = _make_service(), _make_service()
    with patch.object(ChatCompletions, "create", return_value="mocked") as create:
        assert first.completions("m", _MESSAGES) == "mocked"
        assert second.completions.create("m", _MESSAGES) == "mocked"
    assert create.call_count == 2
    first._session.post.assert_not_called()
    second._session.post.assert_not_called()
