"""Chat service — completions and streaming."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._http import RetryPolicy, coerce_retry, post_chat_completion
from ._streaming import SSEStream

if TYPE_CHECKING:
    import requests


class ChatService:
    """Access the ``/chat/completions`` endpoint.

    Args:
        session: A :class:`requests.Session` with auth headers configured.
        base_url: The SAIA API base URL.
    """

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        *,
        retry: RetryPolicy | bool | None = None,
    ):
        self._session = session
        self._base_url = base_url
        self._retry = coerce_retry(retry)

    def completions(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs,
    ) -> dict | SSEStream:
        """Send a chat completion request.

        Args:
            model: Model identifier (e.g. ``"meta-llama-3.1-8b-instruct"``).
            messages: List of message dicts with ``"role"`` and ``"content"`` keys.
            temperature: Sampling temperature (0–2).
            top_p: Nucleus sampling parameter (0–1).
            max_tokens: Maximum tokens to generate.
            stream: If ``True``, return a generator yielding chunks.
            **kwargs: Additional parameters forwarded to the API.

        Returns:
            When ``stream=False``: the API response dict, with an extra
            ``"_rate_limits"`` key — a JSON-serializable dict of the current
            rate-limit headers (see :class:`~saia_python.RateLimitInfo`).
            When ``stream=True``: an ``SSEStream`` — iterate it for the
            response chunks; its ``rate_limits`` attribute exposes the same
            dict (available immediately, from the response headers).
        """
        body = {"model": model, "messages": messages, **kwargs}
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        return post_chat_completion(
            self._session,
            f"{self._base_url}/chat/completions",
            body,
            stream=stream,
            policy=self._retry,
        )

    def __repr__(self):
        return f"ChatService(base_url={self._base_url!r})"
