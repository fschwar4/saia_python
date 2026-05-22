"""Helpers for extracting fields from OpenAI-style API responses.

The SAIA Chat AI and ARCANA RAG endpoints both return the canonical
OpenAI ``ChatCompletion`` envelope::

    {
        "choices": [
            {"message": {"role": "assistant", "content": "<text>"}, ...}
        ],
        ...
    }

Every caller eventually writes the same lookup chain. The helpers in
this module make that lookup safe and uniform — empty ``choices`` lists
and missing ``content`` fields return ``""`` (with a logged warning) so
downstream string-handling code doesn't have to special-case them.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def text_of(response: dict) -> str:
    """Extract the assistant message content from a chat / RAG response.

    Reaches into ``response["choices"][0]["message"]["content"]`` with
    full nil-safety: an empty ``choices`` list, a missing ``message``
    key, or a ``None`` ``content`` field all collapse to ``""`` rather
    than raising. Both empty-response cases log a warning at this
    module's logger so silent regressions surface in logs.

    Works for the response shape returned by:

    - :meth:`saia_python.ChatService.completions`
    - :meth:`saia_python.ArcanaService.chat`
    - ``client.openai.chat.completions.create(...).model_dump()``

    Args:
        response: An OpenAI-style ChatCompletion response dict.

    Returns:
        The first choice's assistant content string, or ``""`` if the
        response carries no usable content.

    Example::

        resp = client.arcana.chat(
            model="...", messages=[...], arcana_id="...",
        )
        answer = saia_python.text_of(resp)
    """
    choices = response.get("choices") or []
    if not choices:
        log.warning(
            "text_of: response has no choices; keys=%s",
            list(response.keys()),
        )
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        log.warning(
            "text_of: first choice has empty content; finish_reason=%r",
            choices[0].get("finish_reason"),
        )
        return ""
    return str(content)
