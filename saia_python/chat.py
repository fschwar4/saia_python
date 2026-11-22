"""Chat service — completions and streaming."""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

from ._http import RetryPolicy, coerce_retry, post_generation, resolve_retry
from ._payloads import build_chat_body
from ._streaming import SSEStream
from .structured import ModelT, parse_structured, response_format_for

if TYPE_CHECKING:
    import requests


class ChatCompletions:
    """``client.chat.completions``: send chat completions with :meth:`create`.

    ``client.chat.completions.create(...)`` is the OpenAI SDK's call form, so
    the native call and ``client.openai.chat.completions.create(...)`` differ
    by one word. Calling the object itself, ``client.chat.completions(...)``,
    does the same as :meth:`create`; that older form keeps working.

    The object keeps nothing but its :class:`ChatService` and reads the
    session, base URL and retry policy from it on every call.

    Args:
        service: The chat service whose session, base URL and retry policy
            the calls use.
    """

    def __init__(self, service: ChatService):
        self._service = service

    def create(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        retry: RetryPolicy | bool | None = None,
        **kwargs: Any,
    ) -> dict | SSEStream:
        """Send a chat completion request.

        Read the answer with :func:`~saia_python.text_of` and the token counts
        with :func:`~saia_python.usage_of`. For a stream,
        :func:`~saia_python.iter_text` yields the text and its iterator's
        :attr:`~saia_python.TextIterator.usage` holds the counts.

        Args:
            model: Model identifier (e.g. ``"qwen3-30b-a3b-instruct-2507"``).
            messages: List of message dicts with ``"role"`` and ``"content"`` keys.
            temperature: Sampling temperature (0–2).
            top_p: Nucleus sampling parameter (0–1).
            max_tokens: Maximum tokens to generate.
            stream: If ``True``, return an :class:`SSEStream` of chunk dicts.
            retry: Overrides the service's rate-limit retry policy for this
                call (``False`` fails fast on a 429).
            **kwargs: Additional parameters forwarded to the API.

        Returns:
            When ``stream=False``: the API response dict, with an extra
            ``"_rate_limits"`` key — a JSON-serializable dict of the current
            rate-limit headers (see :class:`~saia_python.RateLimitInfo`).
            When ``stream=True``: an ``SSEStream`` — iterate it for the
            response chunks; its ``rate_limits`` attribute exposes the same
            dict (available immediately, from the response headers).
        """
        service = self._service
        body = build_chat_body(
            model,
            messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            **kwargs,
        )
        return post_generation(
            service._session,
            f"{service._base_url}/chat/completions",
            body,
            stream=stream,
            policy=resolve_retry(service._retry, retry),
        )

    # Calling the object is the same as create. Type checkers see create's
    # signature; at runtime create is looked up on each call, so a test that
    # patches create also catches the call form client.chat.completions(...).
    if TYPE_CHECKING:
        __call__ = create
    else:

        def __call__(self, *args, **kwargs):
            return self.create(*args, **kwargs)

    def __repr__(self) -> str:
        return f"ChatCompletions(base_url={self._service._base_url!r})"


class ChatService:
    """Access the ``/chat/completions`` endpoint.

    Send a chat completion with ``completions.create(...)`` (see
    :class:`ChatCompletions`), or get the answer as a validated Pydantic model
    with :meth:`completions_structured`.

    Args:
        session: A :class:`requests.Session` with auth headers configured.
        base_url: The SAIA API base URL.
        retry: The service's rate-limit :class:`~saia_python.RetryPolicy`
            (``None`` gives the defaults, ``False`` disables retry).
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

    @cached_property
    def completions(self) -> ChatCompletions:
        """The chat completions; send a request with :meth:`~ChatCompletions.create`.

        The object is built on first access and then kept on the service, so
        ``client.chat.completions`` returns the same object every time, and a
        test can replace it with ``patch.object(client.chat, "completions", …)``.
        To mock the calls instead, patch its ``create``; that catches the call
        form ``client.chat.completions(...)`` and :meth:`completions_structured`
        too.
        """
        return ChatCompletions(self)

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
        **kwargs: Any,
    ) -> ModelT:
        """Send a chat completion and return the answer as a validated model.

        Sends ``response_model``'s JSON Schema as the ``response_format`` (see
        :func:`~saia_python.response_format_for`), which SAIA enforces on the
        server, then validates the answer into an instance (see
        :func:`~saia_python.parse_structured`). Non-streaming only. To keep the
        raw response too (``usage``, ``_rate_limits``), call those two helpers
        around :meth:`completions.create <ChatCompletions.create>` yourself.

        Args:
            model: Model identifier (e.g. ``"qwen3-30b-a3b-instruct-2507"``).
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
                call, as in :meth:`completions.create <ChatCompletions.create>`.
            **kwargs: Additional parameters forwarded to the API.

        Returns:
            An instance of ``response_model``.

        Raises:
            StructuredOutputError: The response holds no answer that validates,
                e.g. because the token budget ran out (``finish_reason`` is
                ``"length"``). The error keeps the full response, ``usage``
                included.
        """
        response = self.completions.create(
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
