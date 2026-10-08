"""Tests for saia_python._streaming — SSE line parsing."""

import json
from unittest.mock import MagicMock

import pytest

from saia_python._streaming import SSEStream, iter_sse
from saia_python.exceptions import AuthenticationError


def _make_response(lines, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.iter_lines.return_value = iter(lines)
    return resp


class TestIterSse:
    def test_normal_chunks(self):
        resp = _make_response(
            [
                'data: {"choices": [{"delta": {"content": "Hello"}}]}',
                'data: {"choices": [{"delta": {"content": " world"}}]}',
                "data: [DONE]",
            ]
        )
        chunks = list(iter_sse(resp))
        assert len(chunks) == 2
        assert chunks[0]["choices"][0]["delta"]["content"] == "Hello"

    def test_done_terminates(self):
        resp = _make_response(
            [
                'data: {"value": 1}',
                "data: [DONE]",
                'data: {"value": 2}',  # must not be yielded
            ]
        )
        chunks = list(iter_sse(resp))
        assert len(chunks) == 1

    def test_malformed_json_skipped(self):
        resp = _make_response(
            [
                'data: {"valid": true}',
                "data: {not json",
                'data: {"also_valid": true}',
                "data: [DONE]",
            ]
        )
        chunks = list(iter_sse(resp))
        assert len(chunks) == 2

    def test_no_space_after_data_colon(self):
        resp = _make_response(
            [
                'data:{"compact": true}',
                "data: [DONE]",
            ]
        )
        chunks = list(iter_sse(resp))
        assert len(chunks) == 1
        assert chunks[0]["compact"] is True

    def test_error_response_raises(self):
        resp = _make_response([], status_code=401)
        resp.text = "Unauthorized"
        with pytest.raises(AuthenticationError):
            list(iter_sse(resp))


class TestSSEStream:
    def test_exposes_rate_limits_and_chunks(self):
        resp = _make_response(
            [
                'data: {"choices": [{"delta": {"content": "Hi"}}]}',
                "data: [DONE]",
            ]
        )
        resp.headers = {
            "x-ratelimit-limit-minute": "30",
            "x-ratelimit-remaining-minute": "29",
        }
        stream = SSEStream(resp)

        # Rate limits available immediately, as a JSON-serializable dict.
        assert stream.rate_limits["limit_minute"] == 30
        assert stream.rate_limits["remaining_minute"] == 29

        chunks = list(stream)
        assert len(chunks) == 1
        assert chunks[0]["choices"][0]["delta"]["content"] == "Hi"

    def test_close_releases_response_even_if_not_iterated(self):
        resp = _make_response(["data: [DONE]"])
        resp.headers = {}
        stream = SSEStream(resp)
        stream.close()
        resp.close.assert_called()

    def test_keeps_trailing_usage_chunk_with_empty_choices(self):
        # SAIA ends every chat stream with a chunk that has no choices but carries
        # the token usage, even without stream_options.include_usage. Callers bill
        # from it, so the stream must hand it over unchanged.
        usage_chunk = {
            "choices": [],
            "usage": {
                "prompt_tokens": 104,
                "total_tokens": 124,
                "completion_tokens": 20,
            },
        }
        resp = _make_response(
            [
                'data: {"choices": [{"delta": {"content": "Hi"}}]}',
                f"data: {json.dumps(usage_chunk)}",
                "data: [DONE]",
            ]
        )
        resp.headers = {}
        chunks = list(SSEStream(resp))
        assert chunks[-1] == usage_chunk
