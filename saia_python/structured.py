"""Structured output — a Pydantic model in, a validated instance out.

SAIA enforces a ``json_schema`` ``response_format`` on the server: its inference
backend (vLLM) compiles the schema into a grammar and blocks every token that
would break it, so the answer matches the schema by construction and needs no
validate-and-retry loop. This module covers the two client-side ends:

- :func:`response_format_for` turns a Pydantic model into the
  ``response_format`` request field.
- :func:`parse_structured` validates a chat response back into the model, and
  raises :class:`~saia_python.StructuredOutputError` with the reason when there
  is nothing usable — most often a reasoning model that spent its
  ``max_tokens`` thinking.

:meth:`ChatService.completions_structured
<saia_python.chat.ChatService.completions_structured>` does both in one call.
Use the two helpers directly when you also need the raw response, e.g. its
``usage``::

    resp = client.chat.completions(
        model, messages, response_format=response_format_for(Invoice)
    )
    invoice = parse_structured(resp, Invoice)
    tokens = resp["usage"]["total_tokens"]

Needs Pydantic v2, which you already have if you define a model; the package
itself imports it only inside :func:`parse_structured`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypeVar

from .exceptions import StructuredOutputError

if TYPE_CHECKING:
    from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound="BaseModel")

_TOKEN_HINT = (
    "Reasoning models spend tokens thinking before they answer: raise max_tokens, "
    "or turn thinking off where the chat template allows it (e.g. Qwen: "
    "chat_template_kwargs={'enable_thinking': False})."
)


def response_format_for(response_model: type[BaseModel]) -> dict:
    """Build the ``response_format`` request field for a Pydantic model.

    ``strict`` is left unset: SAIA's backends enforce the schema either way,
    whereas OpenAI's strict mode would reject a plain Pydantic schema (it
    requires ``additionalProperties: false`` on every object).

    Args:
        response_model: A Pydantic v2 model class.

    Returns:
        ``{"type": "json_schema", "json_schema": {"name": ..., "schema": ...}}``
        with the model's JSON Schema, named after the class (characters outside
        ``a-z A-Z 0-9 _ -``, such as a generic's brackets, become ``_``).
    """
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", response_model.__name__)[:64]
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "schema": response_model.model_json_schema()},
    }


def parse_structured(response: dict, response_model: type[ModelT]) -> ModelT:
    """Validate a chat response's answer into ``response_model``.

    Reads the first choice's ``content`` — the JSON string the model wrote — and
    validates it with ``response_model.model_validate_json``. Works on any
    OpenAI-style ChatCompletion dict, such as the one
    :meth:`~saia_python.chat.ChatService.completions` returns.

    Args:
        response: A chat completion response dict.
        response_model: The Pydantic v2 model class to validate into.

    Returns:
        The validated ``response_model`` instance.

    Raises:
        StructuredOutputError: When there is no usable answer: no choices; no
            content (a reasoning model that ran out of tokens while thinking
            returns ``content: None`` with ``finish_reason: "length"``); an
            answer cut off at ``max_tokens``; or one that fails validation, with
            the :class:`pydantic.ValidationError` chained as the cause.
    """
    from pydantic import ValidationError

    name = response_model.__name__
    choices = response.get("choices") or []
    if not choices:
        raise StructuredOutputError(
            f"{name}: the response has no choices", response=response
        )
    finish_reason = choices[0].get("finish_reason")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        if finish_reason == "length":
            reason = f"the model ran out of tokens before answering. {_TOKEN_HINT}"
        elif message.get("refusal"):
            reason = f"the model refused: {message['refusal']}"
        else:
            reason = f"the response has no content (finish_reason={finish_reason!r})"
        raise StructuredOutputError(
            f"{name}: {reason}", response=response, finish_reason=finish_reason
        )
    try:
        return response_model.model_validate_json(content)
    except ValidationError as exc:
        # Validate before blaming finish_reason: an answer can be complete even
        # when generation hit the limit afterwards (e.g. trailing whitespace).
        if finish_reason == "length":
            reason = f"the answer was cut off at max_tokens. {_TOKEN_HINT}"
        else:
            error = exc.errors()[0]
            where = ".".join(str(part) for part in error["loc"])
            detail = f"{where}: {error['msg']}" if where else error["msg"]
            if exc.error_count() > 1:
                detail += f"; {exc.error_count() - 1} more"
            reason = f"the answer failed validation ({detail})"
        raise StructuredOutputError(
            f"{name}: {reason}", response=response, finish_reason=finish_reason
        ) from exc
