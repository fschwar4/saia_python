"""Messages service — Anthropic's Messages format on ``/messages``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._http import RetryPolicy, coerce_retry, post_generation, resolve_retry
from ._payloads import build_message_body
from ._streaming import SSEStream

if TYPE_CHECKING:
    import requests


class MessagesService:
    """Access the ``/messages`` endpoint (Anthropic's Messages format).

    Note:
        As of 2026-11-22, GWDG's documentation does not list ``/messages``;
        the route works and answers in Anthropic's Messages format (checked
        live that day).

    What SAIA supports there, as seen on 2026-11-19:

    - **A required token limit.** A call without ``max_tokens`` gets a 400,
      so :meth:`create` takes it as a positional argument.
    - **No extra headers.** The session's Bearer auth is enough; SAIA needs
      no ``anthropic-version`` header.
    - **Tool calling** (``tools`` with an ``input_schema``, ``tool_choice``)
      works and passes through ``**kwargs``. For structured output, force a
      tool (``tool_choice={"type": "tool", "name": …}``) and read the
      ``input`` of its ``tool_use`` block: the route ignores
      ``response_format``.
    - **Reasoning models** send their reasoning as a ``thinking`` block
      before the answer.
    - **No ARCANA.** The route accepts the ARCANA fields but ignores them;
      RAG stays on :meth:`ArcanaService.chat
      <saia_python.arcana.ArcanaService.chat>`.

    The OpenAI SDK cannot send this format, so ``client.openai`` has no
    counterpart; this service needs no SDK.

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

    def create(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int,
        *,
        system: str | list[dict] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        stream: bool = False,
        retry: RetryPolicy | bool | None = None,
        **kwargs: Any,
    ) -> dict | SSEStream:
        """Create a message.

        Read the answer with :func:`~saia_python.text_of`, which joins the
        ``text`` blocks and skips ``thinking``, and the token counts with
        :func:`~saia_python.usage_of`. For a stream,
        :func:`~saia_python.iter_text` yields the text and its iterator's
        :attr:`~saia_python.TextIterator.usage` holds the counts.

        Args:
            model: Model identifier (e.g. ``"qwen3-30b-a3b-instruct-2507"``).
            messages: The conversation, as ``user`` and ``assistant`` turns
                whose ``content`` is a string or a list of content blocks.
                For a tool round trip, add the assistant turn with the
                ``tool_use`` block, then a user turn with a ``tool_result``
                block (``tool_use_id``, ``content``). The system prompt goes
                in ``system``, not here.
            max_tokens: Maximum tokens to generate, thinking included.
                Required, since SAIA rejects a call without it. When they run
                out, ``stop_reason`` is ``"max_tokens"`` and the text so far
                is returned, not an error. Reasoning models think before
                they answer, so leave room.
            system: The system prompt: a string, or a list of ``text``
                blocks.
            temperature: Sampling temperature.
            top_p: Nucleus sampling parameter (0–1).
            stream: If ``True``, return an :class:`SSEStream` of event dicts,
                each with a ``type`` (``message_start`` … ``message_stop``).
            retry: Overrides the service's rate-limit retry policy for this
                call (``False`` fails fast on a 429).
            **kwargs: Additional parameters forwarded to the API (``tools``,
                ``tool_choice``, ``stop_sequences``, ``top_k``, …).

        Returns:
            The API response dict (``type: "message"``, with its ``content``
            blocks, ``stop_reason`` and ``usage``) plus an extra
            ``"_rate_limits"`` key, a JSON-serializable dict of the current
            rate-limit headers (see :class:`~saia_python.RateLimitInfo`).
            With ``stream=True``, an :class:`SSEStream` of event dicts
            instead, whose ``rate_limits`` attribute holds the same dict.
            The stream reports the input tokens in ``message_start`` and the
            final counts in ``message_delta``, before its last event,
            ``message_stop``.

        Raises:
            SAIAError: A subclass for an HTTP error, e.g.
                :class:`~saia_python.APIError` for an invalid parameter or
                :class:`~saia_python.RateLimitError` when the 429 retry gives
                up. With ``stream=True`` it is raised once iteration starts.
        """
        body = build_message_body(
            model,
            messages,
            max_tokens,
            system=system,
            temperature=temperature,
            top_p=top_p,
            **kwargs,
        )
        return post_generation(
            self._session,
            f"{self._base_url}/messages",
            body,
            stream=stream,
            policy=resolve_retry(self._retry, retry),
        )

    def __repr__(self) -> str:
        return f"MessagesService(base_url={self._base_url!r})"
