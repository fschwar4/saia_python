"""Tests for saia_python.voice — blocking vs. Future (wait=False) return modes."""

import concurrent.futures
from unittest.mock import MagicMock

import pytest

from saia_python.voice import VoiceService


def _make_service() -> VoiceService:
    """Build a VoiceService with a mocked session (no real HTTP)."""
    svc = VoiceService.__new__(VoiceService)
    svc._session = MagicMock()
    svc._base_url = "https://example.com/v1"
    return svc


def _text_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.headers = {"content-type": "text/plain"}
    resp.text = text
    return resp


def test_transcribe_wait_true_returns_text(tmp_path):
    """Default (wait=True) blocks and returns the transcription string."""
    svc = _make_service()
    svc._session.post.return_value = _text_response("hello world")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF....")

    result = svc.transcribe(audio)

    assert result == "hello world"


def test_transcribe_wait_false_returns_resolvable_future(tmp_path):
    """wait=False returns a Future; .result() yields the transcription."""
    svc = _make_service()
    # The background path uses a dedicated Session via _new_session().
    bg_session = MagicMock()
    bg_session.post.return_value = _text_response("async text")
    svc._new_session = MagicMock(return_value=bg_session)

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF....")

    fut = svc.transcribe(audio, wait=False)

    assert isinstance(fut, concurrent.futures.Future)
    assert fut.result(timeout=5) == "async text"
    # The dedicated background Session is closed when the worker finishes.
    bg_session.close.assert_called_once()
    # The shared client Session was NOT used for the backgrounded request.
    svc._session.post.assert_not_called()


def test_transcribe_wait_false_future_propagates_errors(tmp_path):
    """An error in the worker surfaces when the caller awaits .result()."""
    svc = _make_service()
    bg_session = MagicMock()
    bg_session.post.side_effect = RuntimeError("boom")
    svc._new_session = MagicMock(return_value=bg_session)

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"data")

    fut = svc.transcribe(audio, wait=False)

    with pytest.raises(RuntimeError, match="boom"):
        fut.result(timeout=5)
    bg_session.close.assert_called_once()


def test_translate_wait_false_returns_future(tmp_path):
    svc = _make_service()
    bg_session = MagicMock()
    bg_session.post.return_value = _text_response("english text")
    svc._new_session = MagicMock(return_value=bg_session)

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"data")

    fut = svc.translate(audio, wait=False)

    assert fut.result(timeout=5) == "english text"
