"""OpenAI SDK compatibility layer for the SAIA platform.

Provides a factory function that creates an ``openai.OpenAI`` (or
``openai.AsyncOpenAI``) client pre-configured with SAIA credentials
and base URL. This enables direct use of the OpenAI Python SDK and
tools built on it (RAGAS, LangChain, instructor, etc.) against the
SAIA API.
"""

from __future__ import annotations

from typing import Optional


def create_openai_client(
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    key_file: Optional[str] = None,
    async_client: bool = False,
):
    """Create an OpenAI client configured for the SAIA platform.

    Reuses the same credential and base URL resolution as
    :class:`~saia_python.SAIAClient`: environment variables, ``.env``,
    ``.saia_api``, and ``config.toml`` are checked automatically when
    parameters are omitted.

    Args:
        api_key: Explicit API key. If omitted, resolved via
            :func:`~saia_python.load_api_key`.
        base_url: Explicit base URL. If omitted, resolved via
            :func:`~saia_python.client.resolve_base_url`.
        key_file: Path to a ``.saia_api`` or ``.env`` file. Ignored
            when ``api_key`` is provided.
        async_client: If ``True``, return an ``openai.AsyncOpenAI``
            instance instead of ``openai.OpenAI``.

    Returns:
        An ``openai.OpenAI`` or ``openai.AsyncOpenAI`` instance.

    Example::

        from saia_python import create_openai_client

        client = create_openai_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-instruct",
            messages=[{"role": "user", "content": "Hello!"}],
        )

        # Embeddings
        embedding = client.embeddings.create(
            model="e5-mistral-7b-instruct",
            input="Text to embed",
        )
    """
    try:
        import openai
    except ImportError as exc:
        raise ImportError(
            "The OpenAI compatibility layer requires the optional 'openai' "
            "dependency. Install it with:\n"
            "    pip install saia-python[openai]"
        ) from exc

    from .auth import load_api_key
    from .client import resolve_base_url

    resolved_key = api_key if api_key is not None else load_api_key(key_file)
    resolved_url = resolve_base_url(base_url)

    cls = openai.AsyncOpenAI if async_client else openai.OpenAI
    return cls(api_key=resolved_key, base_url=resolved_url)
