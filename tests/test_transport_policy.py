"""Tests for the rate-limit transport-policy seam (``saia_python._http``).

Covers ``RetryPolicy`` / ``coerce_retry``, the wait planner ``_plan``, and
``execute``'s 429 retry behavior — all offline with a mocked session and an
injected ``sleep`` so nothing actually blocks.
"""

from unittest.mock import MagicMock

import pytest

from saia_python._http import (
    RetryPolicy,
    _plan,
    coerce_retry,
    execute,
    post_chat_completion,
)
from saia_python._streaming import SSEStream
from saia_python.exceptions import RateLimitError
from saia_python.rate_limits import RateLimitInfo


def _resp(status_code, headers=None, *, ok=None, json_body=None):
    r = MagicMock()
    r.status_code = status_code
    r.headers = headers or {}
    r.ok = (status_code < 400) if ok is None else ok
    if json_body is not None:
        r.json.return_value = json_body
    return r


def _session(responses):
    """A mock session whose ``.post`` returns the queued responses in order."""
    s = MagicMock()
    s.post.side_effect = list(responses)
    return s


class _Recorder:
    """Injectable sleep that records durations instead of blocking."""

    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


class TestCoerceAndApplies:
    def test_none_and_true_default_on(self):
        assert coerce_retry(None).on_rate_limit is True
        assert coerce_retry(True).on_rate_limit is True

    def test_false_disables(self):
        assert coerce_retry(False).on_rate_limit is False

    def test_policy_passthrough(self):
        p = RetryPolicy(max_retries=9)
        assert coerce_retry(p) is p

    def test_applies_idempotent(self):
        assert RetryPolicy().applies(idempotent=True) is True

    def test_applies_blocks_mutation_by_default(self):
        assert RetryPolicy().applies(idempotent=False) is False

    def test_applies_mutation_when_opted_in(self):
        assert RetryPolicy(retry_mutations=True).applies(idempotent=False) is True

    def test_applies_off_never(self):
        assert RetryPolicy(on_rate_limit=False).applies(idempotent=True) is False


class TestPlan:
    def test_reset_within_cap_waits_reset_plus_one(self):
        p = RetryPolicy(max_waiting_time=60)
        assert _plan(RateLimitInfo(reset_seconds=26), p, 0) == 27.0

    def test_reset_beyond_cap_gives_up(self):
        p = RetryPolicy(max_waiting_time=60)
        assert _plan(RateLimitInfo(reset_seconds=200), p, 0) is None

    def test_long_window_exhausted_gives_up_even_with_reset(self):
        p = RetryPolicy(max_waiting_time=60)
        # remaining_hour == 0 → the hour reset is unknowable → fail fast
        info = RateLimitInfo(reset_seconds=5, remaining_hour=0)
        assert _plan(info, p, 0) is None

    def test_reset_path_respects_max_retries(self):
        p = RetryPolicy(max_retries=2)
        assert _plan(RateLimitInfo(reset_seconds=5), p, 1) == 6.0
        assert _plan(RateLimitInfo(reset_seconds=5), p, 2) is None

    def test_fallback_when_no_reset(self):
        p = RetryPolicy(fallback_wait=31, fallback_max_retries=2)
        assert _plan(RateLimitInfo(), p, 0) == 31
        assert _plan(RateLimitInfo(), p, 1) == 31
        assert _plan(RateLimitInfo(), p, 2) is None


class TestExecute:
    POLICY = RetryPolicy(jitter=(0.0, 0.0))  # deterministic waits

    def test_200_returns_immediately_no_sleep(self):
        sess = _session([_resp(200)])
        sleep = _Recorder()
        resp = execute(
            sess, "post", "u", policy=self.POLICY, idempotent=True, sleep=sleep
        )
        assert resp.status_code == 200
        assert sess.post.call_count == 1
        assert sleep.waits == []

    def test_429_then_200_retries_and_waits_reset(self):
        sess = _session([_resp(429, {"ratelimit-reset": "5"}), _resp(200)])
        sleep = _Recorder()
        resp = execute(
            sess, "post", "u", policy=self.POLICY, idempotent=True, sleep=sleep
        )
        assert resp.status_code == 200
        assert sess.post.call_count == 2
        assert sleep.waits == [6.0]  # reset 5 + 1s buffer

    def test_429_long_window_gives_up_no_sleep(self):
        sess = _session([_resp(429, {"x-ratelimit-remaining-hour": "0"})])
        sleep = _Recorder()
        resp = execute(
            sess, "post", "u", policy=self.POLICY, idempotent=True, sleep=sleep
        )
        assert resp.status_code == 429
        assert sess.post.call_count == 1
        assert sleep.waits == []

    def test_429_reset_beyond_cap_gives_up_no_sleep(self):
        sess = _session([_resp(429, {"ratelimit-reset": "300"})])
        sleep = _Recorder()
        resp = execute(
            sess, "post", "u", policy=self.POLICY, idempotent=True, sleep=sleep
        )
        assert resp.status_code == 429
        assert sleep.waits == []

    def test_429_no_header_uses_fallback_twice_then_gives_up(self):
        sess = _session([_resp(429), _resp(429), _resp(429)])
        sleep = _Recorder()
        resp = execute(
            sess, "post", "u", policy=self.POLICY, idempotent=True, sleep=sleep
        )
        assert resp.status_code == 429
        assert sess.post.call_count == 3  # initial + 2 fallback retries
        assert sleep.waits == [31, 31]

    def test_disabled_policy_no_retry(self):
        sess = _session([_resp(429, {"ratelimit-reset": "5"})])
        sleep = _Recorder()
        resp = execute(
            sess,
            "post",
            "u",
            policy=RetryPolicy(on_rate_limit=False),
            idempotent=True,
            sleep=sleep,
        )
        assert resp.status_code == 429
        assert sess.post.call_count == 1
        assert sleep.waits == []

    def test_mutation_not_retried_by_default(self):
        sess = _session([_resp(429, {"ratelimit-reset": "5"})])
        sleep = _Recorder()
        resp = execute(
            sess, "post", "u", policy=self.POLICY, idempotent=False, sleep=sleep
        )
        assert resp.status_code == 429
        assert sess.post.call_count == 1

    def test_mutation_retried_when_opted_in(self):
        pol = RetryPolicy(jitter=(0.0, 0.0), retry_mutations=True)
        sess = _session([_resp(429, {"ratelimit-reset": "5"}), _resp(200)])
        sleep = _Recorder()
        resp = execute(sess, "post", "u", policy=pol, idempotent=False, sleep=sleep)
        assert resp.status_code == 200
        assert sess.post.call_count == 2

    def test_connection_closed_before_retry(self):
        r429 = _resp(429, {"ratelimit-reset": "5"})
        sess = _session([r429, _resp(200)])
        execute(
            sess, "post", "u", policy=self.POLICY, idempotent=True, sleep=_Recorder()
        )
        r429.close.assert_called_once()

    def test_jitter_within_bounds(self):
        pol = RetryPolicy(jitter=(0.0, 2.0))
        sess = _session([_resp(429, {"ratelimit-reset": "5"}), _resp(200)])
        sleep = _Recorder()
        execute(sess, "post", "u", policy=pol, idempotent=True, sleep=sleep)
        assert len(sleep.waits) == 1
        assert 6.0 <= sleep.waits[0] <= 8.0  # reset+1 plus [0,2] jitter


class TestPostChatCompletionRetry:
    def test_non_streaming_retries_then_returns_dict(self):
        sess = _session(
            [
                _resp(429, {"ratelimit-reset": "1"}),
                _resp(
                    200,
                    {"x-ratelimit-remaining-minute": "29"},
                    json_body={"ok": 1},
                ),
            ]
        )
        sleep = _Recorder()
        result = post_chat_completion(
            sess,
            "u",
            {"model": "m"},
            policy=RetryPolicy(jitter=(0.0, 0.0)),
            sleep=sleep,
        )
        assert result["ok"] == 1
        assert result["_rate_limits"]["remaining_minute"] == 29
        assert sess.post.call_count == 2
        assert sleep.waits == [2.0]

    def test_streaming_retries_opening_429_then_returns_stream(self):
        r429 = _resp(429, {"ratelimit-reset": "1"})
        r200 = _resp(200, {"x-ratelimit-remaining-minute": "5"})
        sess = _session([r429, r200])
        sleep = _Recorder()
        stream = post_chat_completion(
            sess,
            "u",
            {"model": "m"},
            stream=True,
            policy=RetryPolicy(jitter=(0.0, 0.0)),
            sleep=sleep,
        )
        assert isinstance(stream, SSEStream)
        assert stream.rate_limits["remaining_minute"] == 5
        assert sess.post.call_count == 2
        r429.close.assert_called_once()

    def test_exhausted_retries_raise_rate_limit_error(self):
        sess = _session([_resp(429), _resp(429), _resp(429)])
        sleep = _Recorder()
        with pytest.raises(RateLimitError):
            post_chat_completion(
                sess,
                "u",
                {"model": "m"},
                policy=RetryPolicy(jitter=(0.0, 0.0)),
                sleep=sleep,
            )
        assert sess.post.call_count == 3
