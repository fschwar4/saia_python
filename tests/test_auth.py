"""Tests for saia_python.auth — API key, ARCANA ID, username, and config discovery."""

import os
from unittest.mock import MagicMock

import pytest

from saia_python._http import RetryPolicy
from saia_python.arcana import ArcanaService, extract_arcana_name
from saia_python.auth import load_api_key, load_arcana_ids, load_username


def _clear_arcana_env(monkeypatch):
    """Remove all ARCANA-related env vars."""
    for key in list(os.environ):
        if "ARCANA" in key:
            monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# load_api_key
# ---------------------------------------------------------------------------


class TestLoadApiKey:
    def test_explicit_path_raw(self, tmp_path):
        f = tmp_path / ".saia_api"
        f.write_text("my-secret-key\n")
        assert load_api_key(f) == "my-secret-key"

    def test_explicit_path_dotenv(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text('SAIA_API_KEY="dotenv-key"\n')
        assert load_api_key(f) == "dotenv-key"

    def test_env_var(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAIA_API_KEY", "env-key")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "env-key"

    def test_env_var_stripped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAIA_API_KEY", "  spaces  ")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "spaces"

    def test_env_var_empty_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAIA_API_KEY", "")
        (tmp_path / ".saia_api").write_text("file-key\n")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "file-key"

    def test_saia_api_file_in_cwd(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAIA_API_KEY", raising=False)
        (tmp_path / ".saia_api").write_text("cwd-key\n")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "cwd-key"

    def test_saia_api_file_skips_comments(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAIA_API_KEY", raising=False)
        (tmp_path / ".saia_api").write_text("# comment\n\nactual-key\n")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "actual-key"

    def test_dotenv_file_in_cwd(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAIA_API_KEY", raising=False)
        (tmp_path / ".env").write_text("OTHER=foo\nSAIA_API_KEY=dotenv-key\n")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "dotenv-key"

    def test_dotenv_strips_quotes(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAIA_API_KEY", raising=False)
        (tmp_path / ".env").write_text("SAIA_API_KEY='quoted-key'\n")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "quoted-key"

    def test_nothing_found_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAIA_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="No SAIA API key found"):
            load_api_key()

    def test_env_var_beats_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAIA_API_KEY", "env-wins")
        (tmp_path / ".saia_api").write_text("file-loses\n")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "env-wins"

    def test_saia_api_beats_dotenv(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAIA_API_KEY", raising=False)
        (tmp_path / ".saia_api").write_text("raw-wins\n")
        (tmp_path / ".env").write_text("SAIA_API_KEY=dotenv-loses\n")
        monkeypatch.chdir(tmp_path)
        assert load_api_key() == "raw-wins"


# ---------------------------------------------------------------------------
# load_arcana_ids — default priority
# ---------------------------------------------------------------------------


class TestLoadArcanaIdsPriority:
    def test_priority_1_env_saia_arcana_id(self, monkeypatch, tmp_path):
        """SAIA_ARCANA_ID in env beats everything."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAIA_ARCANA_ID", "user/env-default")
        (tmp_path / "config.toml").write_text(
            '[saia.arcana]\ndefault = "user/toml-default"\nids = ["user/toml-first"]\n'
        )
        ids = load_arcana_ids()
        assert ids["default"] == "user/env-default"

    def test_priority_2_toml_default(self, monkeypatch, tmp_path):
        """config.toml [saia.arcana] default beats ids array."""
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.toml").write_text(
            '[saia.arcana]\ndefault = "user/toml-default"\nids = ["user/toml-first"]\n'
        )
        ids = load_arcana_ids()
        assert ids["default"] == "user/toml-default"

    def test_priority_3_toml_ids_first(self, monkeypatch, tmp_path):
        """First element of config.toml ids array when no explicit default."""
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.toml").write_text(
            '[saia.arcana]\nids = ["user/first-id", "user/second-id"]\n'
        )
        ids = load_arcana_ids()
        assert ids["default"] == "user/first-id"

    def test_priority_4_numbered_env_first(self, monkeypatch, tmp_path):
        """First numbered SAIA_ARCANA_ID_XX when no other default."""
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAIA_ARCANA_ID_01", "user/numbered-first")
        monkeypatch.setenv("SAIA_ARCANA_ID_02", "user/numbered-second")
        ids = load_arcana_ids()
        assert ids["default"] == "user/numbered-first"

    def test_env_default_beats_toml_default(self, monkeypatch, tmp_path):
        """SAIA_ARCANA_ID in .env file beats config.toml default."""
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("SAIA_ARCANA_ID=user/dotenv-default\n")
        (tmp_path / "config.toml").write_text(
            '[saia.arcana]\ndefault = "user/toml-default"\n'
        )
        ids = load_arcana_ids()
        assert ids["default"] == "user/dotenv-default"


# ---------------------------------------------------------------------------
# load_arcana_ids — source merging
# ---------------------------------------------------------------------------


class TestLoadArcanaIdsSources:
    def test_toml_ids_array(self, monkeypatch, tmp_path):
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.toml").write_text(
            '[saia.arcana]\nids = ["user/a", "user/b", "user/c"]\n'
        )
        ids = load_arcana_ids()
        assert ids["0"] == "user/a"
        assert ids["1"] == "user/b"
        assert ids["2"] == "user/c"

    def test_toml_labels(self, monkeypatch, tmp_path):
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.toml").write_text(
            '[saia.arcana.labels]\nproject_a = "user/id-a"\nproject_b = "user/id-b"\n'
        )
        ids = load_arcana_ids()
        assert ids["project_a"] == "user/id-a"
        assert ids["project_b"] == "user/id-b"

    def test_numbered_env_vars(self, monkeypatch, tmp_path):
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAIA_ARCANA_ID_01", "user/first")
        monkeypatch.setenv("SAIA_ARCANA_ID_02", "user/second")
        ids = load_arcana_ids()
        assert ids["01"] == "user/first"
        assert ids["02"] == "user/second"

    def test_empty_returns_empty_dict(self, monkeypatch, tmp_path):
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        assert load_arcana_ids() == {}

    def test_all_sources_merge(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SAIA_ARCANA_ID", "user/env-default")
        monkeypatch.setenv("SAIA_ARCANA_ID_99", "user/numbered")
        (tmp_path / "config.toml").write_text(
            '[saia.arcana]\nids = ["user/toml-a", "user/toml-b"]\n'
            '[saia.arcana.labels]\nmy_label = "user/labeled"\n'
        )
        ids = load_arcana_ids()
        assert ids["default"] == "user/env-default"
        assert ids["0"] == "user/toml-a"
        assert ids["1"] == "user/toml-b"
        assert ids["my_label"] == "user/labeled"
        assert ids["99"] == "user/numbered"


# ---------------------------------------------------------------------------
# load_arcana_ids — legacy removed
# ---------------------------------------------------------------------------


class TestLoadArcanaIdsLegacyRemoved:
    def test_legacy_arcana_id_ignored(self, monkeypatch, tmp_path):
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ARCANA_ID", "legacy-value")
        ids = load_arcana_ids()
        assert "default" not in ids
        assert "legacy-value" not in ids.values()


# ---------------------------------------------------------------------------
# load_arcana_ids — owner prefix resolution
# ---------------------------------------------------------------------------


class TestArcanaOwnerPrefix:
    """Verify username is prepended to IDs without owner prefix."""

    def test_username_set_id_without_prefix(self, monkeypatch, tmp_path):
        """a) Username configured, ID has no '/' → username prepended."""
        _clear_arcana_env(monkeypatch)
        monkeypatch.delenv("SAIA_USERNAME", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("SAIA_ARCANA_ID=MyArcana\n")
        (tmp_path / "config.toml").write_text('[saia]\nusername = "saiauser123"\n')
        ids = load_arcana_ids()
        assert ids["default"] == "saiauser123/MyArcana"

    def test_no_username_id_with_prefix(self, monkeypatch, tmp_path):
        """b) No username, ID already has '/' → works as-is."""
        _clear_arcana_env(monkeypatch)
        monkeypatch.delenv("SAIA_USERNAME", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("SAIA_ARCANA_ID=saiauser123/MyArcana\n")
        ids = load_arcana_ids()
        assert ids["default"] == "saiauser123/MyArcana"

    def test_both_username_and_prefix(self, monkeypatch, tmp_path):
        """c) Username set and ID already has '/' → ID unchanged."""
        _clear_arcana_env(monkeypatch)
        monkeypatch.delenv("SAIA_USERNAME", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("SAIA_ARCANA_ID=saiauser123/MyArcana\n")
        (tmp_path / "config.toml").write_text('[saia]\nusername = "saiauser123"\n')
        ids = load_arcana_ids()
        assert ids["default"] == "saiauser123/MyArcana"

    def test_no_username_no_prefix_raises(self, monkeypatch, tmp_path):
        """d) No username, ID has no '/' → ValueError."""
        _clear_arcana_env(monkeypatch)
        monkeypatch.delenv("SAIA_USERNAME", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("SAIA_ARCANA_ID=MyArcana\n")
        with pytest.raises(ValueError, match="SAIA_USERNAME is not configured"):
            load_arcana_ids()


# ---------------------------------------------------------------------------
# extract_arcana_name
# ---------------------------------------------------------------------------


class TestExtractArcanaName:
    def test_full_id_strips_owner(self):
        assert extract_arcana_name("saiauser123/My-Arcana-abc123") == "My-Arcana-abc123"

    def test_owner_with_multiple_slashes(self):
        assert extract_arcana_name("user/name/with/slashes") == "name/with/slashes"

    def test_name_with_spaces(self):
        assert extract_arcana_name("user/DLBCL Test-abc") == "DLBCL Test-abc"


# ---------------------------------------------------------------------------
# load_username
# ---------------------------------------------------------------------------


class TestLoadUsername:
    def test_from_toml(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAIA_USERNAME", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.toml").write_text('[saia]\nusername = "toml-user"\n')
        assert load_username() == "toml-user"

    def test_env_beats_toml(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAIA_USERNAME", "env-wins")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config.toml").write_text('[saia]\nusername = "toml-loses"\n')
        assert load_username() == "env-wins"

    def test_none_when_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAIA_USERNAME", raising=False)
        monkeypatch.chdir(tmp_path)
        assert load_username() is None


# ---------------------------------------------------------------------------
# arcana.summary()
# ---------------------------------------------------------------------------


class TestArcanaSummary:
    def test_summary_output(self, monkeypatch, tmp_path):
        _clear_arcana_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("SAIA_ARCANA_ID=user/default-arcana\n")
        (tmp_path / "config.toml").write_text(
            '[saia.arcana]\nids = ["user/arcana-one", "user/arcana-two"]\n'
            '[saia.arcana.labels]\nresearch = "user/research-arcana"\n'
        )
        ids = load_arcana_ids()

        # Mock the service (no real API)
        svc = ArcanaService.__new__(ArcanaService)
        svc._session = MagicMock()
        svc._base_url = "https://example.com/v1"
        svc._arcana_base = "https://example.com/v1/arcanas/api/v1"
        svc._api_key = "test"
        svc._timeout = (10.0, 60.0)
        svc._retry = RetryPolicy()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = [
            {
                "name": "arcana-one",
                "owner_user_name": "user",
                "file_count": 10,
                "index_info": {"index_status": "INDEXED"},
            }
        ]
        svc._session.get.return_value = mock_resp

        output = svc.summary(arcana_ids=ids)

        assert "Configured ARCANA IDs" in output
        assert "user/default-arcana" in output
        assert "research" in output
        assert "Available on server" in output
        assert "INDEXED" in output
