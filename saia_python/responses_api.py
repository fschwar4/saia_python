"""Responses service — OpenAI's Responses API format on ``/responses``.

Named ``responses_api`` because :mod:`saia_python.responses` already holds the
helpers that read results (:func:`~saia_python.text_of` and friends).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._http import RetryPolicy, coerce_retry, post_generation, resolve_retry
from ._payloads import build_response_body
from ._streaming import SSEStream

if TYPE_CHECKING:
    import requests


class ResponsesService:
    """Access the ``/responses`` endpoint (OpenAI's Responses API format).

    Note:
        As of 2026-11-20, GWDG's documentation does not list
        ``/responses``; the route works and answers with genuine Responses
        API objects (checked live that day).

    What SAIA supports there, as seen on 2026-11-19:

    - **Stateless only.** ``store`` is accepted, but nothing can be
      retrieved afterwards, and ``previous_response_id`` gets a 404. Send the
      whole conversation as an ``input`` list, as chat sends ``messages``.
    - **Tool calling** (``tools``, ``tool_choice``) and **structured output**
      (``text={"format": {"type": "json_schema", …}}``) work and pass
      through ``**kwargs``.
    - **No ARCANA.** The route accepts the ARCANA fields but ignores them;
      RAG stays on :meth:`ArcanaService.chat
      <saia_python.arcana.ArcanaService.chat>`.

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
        input: str | list[dict],
        *,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        stream: bool = False,
        retry: RetryPolicy | bool | None = None,
        **kwargs: Any,
    ) -> dict | SSEStream:
        """Create a response.

        Read the answer with :func:`~saia_python.text_of`, which joins the
        ``output_text`` parts of the message items and skips reasoning, a
        stream's text with :func:`~saia_python.iter_text`, and the token
        counts with :func:`~saia_python.usage_of`. The OpenAI SDK equivalent
        is ``client.openai.responses.create(...)``, which returns a typed
        ``Response``; the same helpers read it.

        Args:
            model: Model identifier (e.g. ``"qwen3-30b-a3b-instruct-2507"``).
            input: The prompt: a string, or a list of input items such as
                messages (``{"role": "user", "content": "…"}``) and, for a
                tool round trip, the model's ``function_call`` item followed
                by a ``function_call_output`` item.
            instructions: The system prompt.
            max_output_tokens: Maximum tokens to generate, reasoning
                included. When they run out, ``status`` is ``"incomplete"``
                and the text so far is returned, not an error. Reasoning
                models think before they answer (in a separate ``reasoning``
                output item), so leave room.
            temperature: Sampling temperature (0–2).
            top_p: Nucleus sampling parameter (0–1).
            stream: If ``True``, return an :class:`SSEStream` of event dicts,
                each with a ``type`` (``response.created`` …
                ``response.completed``).
            retry: Overrides the service's rate-limit retry policy for this
                call (``False`` fails fast on a 429).
            **kwargs: Additional parameters forwarded to the API (``tools``,
                ``tool_choice``, ``text``, ``reasoning``, …).

        Returns:
            The API response dict (``object: "response"``, with its
            ``output`` items, ``status`` and ``usage``) plus an extra
            ``"_rate_limits"`` key, a JSON-serializable dict of the current
            rate-limit headers (see :class:`~saia_python.RateLimitInfo`).
            With ``stream=True``, an :class:`SSEStream` of event dicts
            instead, whose ``rate_limits`` attribute holds the same dict; the
            last event, ``response.completed``, carries the full response,
            ``usage`` included.

        Raises:
            SAIAError: A subclass for an HTTP error, e.g.
                :class:`~saia_python.APIError` for an invalid parameter or
                :class:`~saia_python.RateLimitError` when the 429 retry gives
                up. With ``stream=True`` it is raised once iteration starts.
        """
        body = build_response_body(
            model,
            input,
            instructions=instructions,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            top_p=top_p,
            **kwargs,
        )
        return post_generation(
            self._session,
            f"{self._base_url}/responses",
            body,
            stream=stream,
            policy=resolve_retry(self._retry, retry),
        )

    def __repr__(self) -> str:
        return f"ResponsesService(base_url={self._base_url!r})"
