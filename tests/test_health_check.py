"""Tests for SAIAClient.health_check."""

from unittest.mock import MagicMock, patch

from saia_python import SAIAClient


def _make_client() -> SAIAClient:
    """Build a SAIAClient without going through auth / network."""
    client = SAIAClient.__new__(SAIAClient)
    client._api_key = "test-key"
    client._base_url = "https://example.com/v1"
    client._session = MagicMock()
    client._chat = None
    client._voice = None
    client._models = None
    client._arcana = None
    client._documents = None
    client._openai = None
    client._openai_async = None
    return client


def test_health_check_returns_true_on_full_success():
    client = _make_client()
    with patch.object(client, "arcana_heartbeat", return_value=True):
        client._models = MagicMock()
        client._models.list_ids.return_value = ["m1", "m2", "m3"]
        assert client.health_check() is True


def test_health_check_verbose_returns_full_diagnostic():
    client = _make_client()
    with patch.object(client, "arcana_heartbeat", return_value=True):
        client._models = MagicMock()
        client._models.list_ids.return_value = ["m1", "m2"]
        details = client.health_check(verbose=True)
    assert details["ok"] is True
    assert details["models_ok"] is True
    assert details["model_count"] == 2
    assert details["arcana_ok"] is True
    assert details["base_url"] == "https://example.com/v1"
    assert details["error"] is None


def test_health_check_returns_false_when_models_call_fails():
    client = _make_client()
    with patch.object(client, "arcana_heartbeat", return_value=True):
        client._models = MagicMock()
        client._models.list_ids.side_effect = RuntimeError("boom")
        assert client.health_check() is False


def test_health_check_verbose_surfaces_models_error():
    client = _make_client()
    with patch.object(client, "arcana_heartbeat", return_value=True):
        client._models = MagicMock()
        client._models.list_ids.side_effect = RuntimeError("auth failed")
        details = client.health_check(verbose=True)
    assert details["ok"] is False
    assert details["models_ok"] is False
    assert details["model_count"] == 0
    assert details["arcana_ok"] is True
    assert "auth failed" in details["error"]


def test_health_check_returns_false_when_arcana_heartbeat_fails():
    client = _make_client()
    with patch.object(client, "arcana_heartbeat", return_value=False):
        client._models = MagicMock()
        client._models.list_ids.return_value = ["m1"]
        assert client.health_check() is False


def test_health_check_verbose_surfaces_arcana_failure():
    client = _make_client()
    with patch.object(client, "arcana_heartbeat", return_value=False):
        client._models = MagicMock()
        client._models.list_ids.return_value = ["m1"]
        details = client.health_check(verbose=True)
    assert details["ok"] is False
    assert details["models_ok"] is True
    assert details["arcana_ok"] is False
    assert "arcana" in details["error"]
