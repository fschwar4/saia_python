"""Completions service — raw-text completion on ``/completions``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._http import RetryPolicy, coerce_retry, post_generation, resolve_retry
from ._payloads import build_completion_body
from ._streaming import SSEStream

if TYPE_CHECKING:
    import requests


class CompletionsService:
    """Access the ``/completions`` endpoint: the model continues a prompt.

    Unlike chat, no chat template is applied and there are no roles: the
    model sees ``prompt`` verbatim and writes what comes next. That suits
    raw continuation and few-shot prompts written as plain text. For a
    conversation, an instruction or structured output, use
    :class:`~saia_python.chat.ChatService`.

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
        prompt: str | list[str] | list[int] | list[list[int]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        stream: bool = False,
        retry: RetryPolicy | bool | None = None,
        **kwargs: Any,
    ) -> dict | SSEStream:
        """Complete a prompt as raw text.

        Read the answer with :func:`~saia_python.text_of`, a stream's text
        with :func:`~saia_python.iter_text`, and the token counts with
        :func:`~saia_python.usage_of`. The OpenAI SDK equivalent is
        ``client.openai.completions.create(...)``, and the same helpers
        read its result.

        Args:
            model: Model identifier (e.g. ``"qwen3-30b-a3b-instruct-2507"``).
            prompt: The text to continue. A list of strings asks for one
                completion per prompt; the response then holds one choice
                each, and :func:`~saia_python.text_of` reads the first.
            max_tokens: Maximum tokens to generate. Set it: when omitted,
                SAIA stops after 16 tokens (seen 2026-11-20), as OpenAI's
                legacy completions API did.
            temperature: Sampling temperature (0–2).
            top_p: Nucleus sampling parameter (0–1).
            stream: If ``True``, return an :class:`SSEStream` of chunks.
            retry: Overrides the service's rate-limit retry policy for this
                call (``False`` fails fast on a 429).
            **kwargs: Additional parameters forwarded to the API (``stop``,
                ``seed``, ``echo``, ``logprobs``, …). ``response_format``
                passes through too, but whether the schema is enforced
                depends on the model (seen 2026-11-19); chat's
                :meth:`~saia_python.chat.ChatService.completions_structured`
                is the reliable way to get structured output.

        Returns:
            The API response dict (``object: "text_completion"``, the text in
            ``choices[0].text``) with an extra ``"_rate_limits"`` key, a
            JSON-serializable dict of the current rate-limit headers (see
            :class:`~saia_python.RateLimitInfo`). With ``stream=True``, an
            :class:`SSEStream` of chunk dicts instead, whose ``rate_limits``
            attribute holds the same dict; its last chunk has empty
            ``choices`` and carries the ``usage``.

        Raises:
            SAIAError: A subclass for an HTTP error, e.g.
                :class:`~saia_python.APIError` for an invalid parameter or
                :class:`~saia_python.RateLimitError` when the 429 retry gives
                up. With ``stream=True`` it is raised once iteration starts.
        """
        body = build_completion_body(
            model,
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            **kwargs,
        )
        return post_generation(
            self._session,
            f"{self._base_url}/completions",
            body,
            stream=stream,
            policy=resolve_retry(self._retry, retry),
        )

    def __repr__(self) -> str:
        return f"CompletionsService(base_url={self._base_url!r})"
