"""Tests for saia_python.openai_compat — OpenAI client factory."""

import openai

from saia_python.openai_compat import create_openai_client


class TestCreateOpenaiClient:

    def test_explicit_credentials(self):
        """Explicit api_key and base_url are passed through without resolution."""
        client = create_openai_client(
            api_key="explicit-key", base_url="https://explicit.example.com/v1"
        )
        assert client.api_key == "explicit-key"
        assert "explicit.example.com" in str(client.base_url)

    def test_auto_resolves_credentials(self, monkeypatch, tmp_path):
        """When no args given, resolves from env/.env/config.toml."""
        monkeypatch.setenv("SAIA_API_KEY", "resolved-key")
        monkeypatch.chdir(tmp_path)

        client = create_openai_client()
        assert client.api_key == "resolved-key"

    def test_async_client(self):
        """async_client=True returns AsyncOpenAI."""
        client = create_openai_client(
            api_key="key", base_url="https://example.com/v1",
            async_client=True,
        )
        assert isinstance(client, openai.AsyncOpenAI)


class TestSAIAClientOpenaiProperty:

    def test_openai_property_lazy_and_cached(self):
        """Property creates on first access and returns same instance."""
        from saia_python import SAIAClient

        client = SAIAClient(api_key="test-key", base_url="https://example.com/v1")
        first = client.openai
        second = client.openai
        assert first is second
