"""Chat service — completions and streaming."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ._http import RetryPolicy, coerce_retry, post_chat_completion, resolve_retry
from ._streaming import SSEStream
from .structured import ModelT, parse_structured, response_format_for

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
        retry: RetryPolicy | bool | None = None,
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
            policy=resolve_retry(self._retry, retry),
        )

    def completions_structured(
        self,
        model: str,
        messages: list[dict],
        response_model: type[ModelT],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        retry: RetryPolicy | bool | None = None,
        **kwargs,
    ) -> ModelT:
        """Send a chat completion and return the answer as a validated model.

        Sends ``response_model``'s JSON Schema as the ``response_format`` (see
        :func:`~saia_python.response_format_for`), which SAIA enforces on the
        server, then validates the answer into an instance (see
        :func:`~saia_python.parse_structured`). Non-streaming only. To keep the
        raw response too (``usage``, ``_rate_limits``), call those two helpers
        around :meth:`completions` yourself.

        Args:
            model: Model identifier (e.g. ``"meta-llama-3.1-8b-instruct"``).
            messages: List of message dicts with ``"role"`` and ``"content"`` keys.
                SAIA uses the schema only to constrain the output and does not
                add it to the prompt, so say what each field should hold.
            response_model: The Pydantic v2 model class the answer must match.
            temperature: Sampling temperature (0–2).
            top_p: Nucleus sampling parameter (0–1).
            max_tokens: Maximum tokens to generate. Reasoning models think
                before they answer, so leave room, or turn thinking off where
                the chat template allows it (e.g. Qwen:
                ``chat_template_kwargs={"enable_thinking": False}``).
            retry: Overrides the service's rate-limit retry policy for this
                call, as in :meth:`completions`.
            **kwargs: Additional parameters forwarded to the API.

        Returns:
            An instance of ``response_model``.

        Raises:
            StructuredOutputError: The response holds no answer that validates,
                e.g. because the token budget ran out (``finish_reason`` is
                ``"length"``). The error keeps the full response, ``usage``
                included.
        """
        response = self.completions(
            model,
            messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=False,
            retry=retry,
            response_format=response_format_for(response_model),
            **kwargs,
        )
        return parse_structured(cast(dict, response), response_model)

    def __repr__(self):
        return f"ChatService(base_url={self._base_url!r})"
