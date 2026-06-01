"""Tests for ModelsService — list / list_raw / list_ids."""

from unittest.mock import MagicMock

from saia_python.models import ModelsService

_ENVELOPE = {
    "object": "list",
    "data": [
        {"id": "llama-3.3-70b-instruct", "object": "model", "owned_by": "saia"},
        {"id": "qwen3-coder-30b", "object": "model", "owned_by": "saia"},
    ],
}


def _service(payload):
    """Build a ModelsService whose session returns ``payload`` from GET /models."""
    session = MagicMock()
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = payload
    session.get.return_value = resp
    return ModelsService(session, "https://example.com/v1"), session


def test_list_raw_returns_envelope_not_unwrapped():
    """list_raw() keeps the OpenAI envelope (unlike list(), which unwraps to
    ``data``), and uses GET /models (not POST)."""
    svc, session = _service(_ENVELOPE)
    result = svc.list_raw()
    assert result["object"] == "list"  # envelope preserved, not unwrapped
    assert result["data"] == _ENVELOPE["data"]
    # GET /models (not POST), and carries the default timeout so it can't hang.
    session.get.assert_called_once_with(
        "https://example.com/v1/models", timeout=(10.0, 60.0)
    )


def test_list_unwraps_data_from_envelope():
    svc, _ = _service(_ENVELOPE)
    assert svc.list() == _ENVELOPE["data"]


def test_list_ids_extracts_ids():
    svc, _ = _service(_ENVELOPE)
    assert svc.list_ids() == ["llama-3.3-70b-instruct", "qwen3-coder-30b"]


def test_list_handles_bare_list_response():
    bare = [{"id": "m1"}, {"id": "m2"}]
    svc, _ = _service(bare)
    assert svc.list() == bare
    assert svc.list_raw() == bare


def test_configured_timeout_is_forwarded():
    """A custom timeout passed to the constructor reaches the GET /models call."""
    session = MagicMock()
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = _ENVELOPE
    session.get.return_value = resp
    svc = ModelsService(session, "https://example.com/v1", timeout=(3.0, 9.0))
    svc.list_raw()
    assert session.get.call_args.kwargs["timeout"] == (3.0, 9.0)
