"""Pure request-body / header builders shared across transports.

Transport-free — no ``Session``, no ``httpx.AsyncClient``, no I/O — so these
helpers are reused **verbatim** by the sync services (:mod:`saia_python.chat`,
:mod:`saia_python.arcana`), the async services (:mod:`saia_python.aio`), and
external gateways that assemble the request themselves (the AVOR adapter builds
its own body so it can inject a per-conversation system prompt, then reuses
:func:`apply_arcana_fields` to keep the ARCANA injection identical to ours).

Keeping the ARCANA injection in ONE place matters: GWDG only routes a request
through the retrieval pipeline when **all three** of ``enable-tools`` + the
``arcana.id`` body field *and* the ``inference-service`` header are present.
Drop any one and the request still returns 200 — but with no retrieval. That
invariant now lives in :func:`apply_arcana_fields` + :func:`arcana_chat_headers`
instead of being retyped at every call site.
"""

from __future__ import annotations

from typing import Any

#: The GWDG gateway value that opts a chat request into the ARCANA retrieval
#: pipeline. Sent as the ``inference-service`` header (see
#: :func:`arcana_chat_headers`); without it retrieval never fires.
INFERENCE_SERVICE = "saia-openai-gateway"


def build_chat_body(
    model: str,
    messages: list[dict],
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> dict:
    """Assemble an OpenAI-shaped ``/chat/completions`` request body.

    The sampling knobs are omitted from the body when ``None`` (so the server's
    own defaults apply) rather than being sent as ``null``. Extra ``kwargs`` are
    merged verbatim, letting callers pass ``stop``, ``stream``, ``seed``, etc.
    """
    body: dict = {"model": model, "messages": messages, **kwargs}
    if temperature is not None:
        body["temperature"] = temperature
    if top_p is not None:
        body["top_p"] = top_p
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return body


def apply_arcana_fields(body: dict, arcana_id: str) -> dict:
    """Return ``body`` with the ARCANA RAG **body** fields injected.

    Adds ``enable-tools: true`` and ``arcana: {"id": arcana_id}``. Returns a
    **new** dict (the input is left unmutated) with the ARCANA fields applied
    last, so they cannot be silently clobbered by an earlier body key. This is
    the body half of the three-part retrieval invariant; pair it with
    :func:`arcana_chat_headers` (or set the ``inference-service`` header
    yourself) for the header half.
    """
    return {**body, "enable-tools": True, "arcana": {"id": arcana_id}}


def arcana_chat_headers(api_key: str, *, extra: dict | None = None) -> dict:
    """Build the header set for an ARCANA chat call.

    ``Bearer`` auth + ``Accept: application/json`` + the ``inference-service``
    gateway header (the header half of the retrieval invariant). ``extra`` is
    merged last, so a caller can add a correlation id (e.g. ``X-Request-ID``)
    without losing the required headers.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "inference-service": INFERENCE_SERVICE,
    }
    if extra:
        headers.update(extra)
    return headers
