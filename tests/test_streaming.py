"""Tests for saia_python._streaming — SSE line parsing."""

from unittest.mock import MagicMock

import pytest

from saia_python._streaming import iter_sse
from saia_python.exceptions import AuthenticationError


def _make_response(lines, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.iter_lines.return_value = iter(lines)
    return resp


class TestIterSse:

    def test_normal_chunks(self):
        resp = _make_response([
            'data: {"choices": [{"delta": {"content": "Hello"}}]}',
            'data: {"choices": [{"delta": {"content": " world"}}]}',
            "data: [DONE]",
        ])
        chunks = list(iter_sse(resp))
        assert len(chunks) == 2
        assert chunks[0]["choices"][0]["delta"]["content"] == "Hello"

    def test_done_terminates(self):
        resp = _make_response([
            'data: {"value": 1}',
            "data: [DONE]",
            'data: {"value": 2}',  # must not be yielded
        ])
        chunks = list(iter_sse(resp))
        assert len(chunks) == 1

    def test_malformed_json_skipped(self):
        resp = _make_response([
            'data: {"valid": true}',
            "data: {not json",
            'data: {"also_valid": true}',
            "data: [DONE]",
        ])
        chunks = list(iter_sse(resp))
        assert len(chunks) == 2

    def test_no_space_after_data_colon(self):
        resp = _make_response([
            'data:{"compact": true}',
            "data: [DONE]",
        ])
        chunks = list(iter_sse(resp))
        assert len(chunks) == 1
        assert chunks[0]["compact"] is True

    def test_error_response_raises(self):
        resp = _make_response([], status_code=401)
        resp.text = "Unauthorized"
        with pytest.raises(AuthenticationError):
            list(iter_sse(resp))
