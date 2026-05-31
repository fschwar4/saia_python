"""OpenAI SDK compatibility layer for the SAIA platform.

Provides a factory function that creates an ``openai.OpenAI`` (or
``openai.AsyncOpenAI``) client pre-configured with SAIA credentials
and base URL. This enables direct use of the OpenAI Python SDK and
tools built on it (RAGAS, LangChain, instructor, etc.) against the
SAIA API.
"""

from __future__ import annotations


def create_openai_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    key_file: str | None = None,
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
            :func:`~saia_python.resolve_base_url`.
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

    from .auth import resolve_credentials

    resolved_key, resolved_url = resolve_credentials(api_key, base_url, key_file)

    cls = openai.AsyncOpenAI if async_client else openai.OpenAI
    return cls(api_key=resolved_key, base_url=resolved_url)
