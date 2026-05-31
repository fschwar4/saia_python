"""Tests for ArcanaService.setup_from_directory.

These tests stub create/upload_directory/generate_index to verify the
composition behaves correctly without making any HTTP calls.
"""

from unittest.mock import MagicMock, patch

from saia_python.arcana import ArcanaService


def _make_service() -> ArcanaService:
    svc = ArcanaService.__new__(ArcanaService)
    svc._session = MagicMock()
    svc._base_url = "https://example.com/v1"
    svc._arcana_base = "https://example.com/v1/arcanas/api/v1"
    svc._api_key = "test"
    return svc


def test_setup_from_directory_composes_create_upload_index():
    svc = _make_service()
    with (
        patch.object(svc, "create") as m_create,
        patch.object(svc, "upload_directory") as m_upload,
        patch.object(svc, "generate_index") as m_index,
    ):
        m_create.return_value = {
            "name": "MyKB-abc-uuid",
            "id": "owner/MyKB-abc-uuid",
            "message": {},
        }
        m_upload.return_value = [{"file_name": "a.md", "status": "uploaded"}]
        m_index.return_value = {"index_status": "INDEXED"}

        result = svc.setup_from_directory(
            "MyKB",
            "./markdown",
            pattern="**/*.md",
            update_toml=True,
            toml_label="my_kb",
            index_timeout=120,
            verbose=False,
        )

    # Each component was called exactly once.
    m_create.assert_called_once_with(
        "MyKB",
        append_uuid=True,
        update_toml=True,
        toml_label="my_kb",
    )
    # upload + index use the UUID-suffixed name returned by create(),
    # not the original display name.
    m_upload.assert_called_once_with(
        "MyKB-abc-uuid",
        "./markdown",
        pattern="**/*.md",
        verbose=False,
    )
    m_index.assert_called_once_with(
        "MyKB-abc-uuid",
        wait=True,
        timeout=120,
    )
    # Return shape carries all three sub-results.
    assert set(result) == {"arcana", "uploads", "index"}
    assert result["arcana"]["id"] == "owner/MyKB-abc-uuid"
    assert result["uploads"][0]["file_name"] == "a.md"
    assert result["index"]["index_status"] == "INDEXED"


def test_setup_from_directory_respects_append_uuid_false():
    """When append_uuid=False, the create() call name flows verbatim."""
    svc = _make_service()
    with (
        patch.object(svc, "create") as m_create,
        patch.object(svc, "upload_directory") as m_upload,
        patch.object(svc, "generate_index") as m_index,
    ):
        m_create.return_value = {"name": "ExactName", "id": "owner/ExactName"}
        m_upload.return_value = []
        m_index.return_value = {"index_status": "INDEXED"}

        svc.setup_from_directory("ExactName", "./dir", append_uuid=False)

    m_create.assert_called_once_with(
        "ExactName",
        append_uuid=False,
        update_toml=False,
        toml_label=None,
    )
    m_upload.assert_called_once_with(
        "ExactName",
        "./dir",
        pattern="*.md",
        verbose=True,
    )


def test_setup_from_directory_propagates_wait_false():
    svc = _make_service()
    with (
        patch.object(svc, "create") as m_create,
        patch.object(svc, "upload_directory") as m_upload,
        patch.object(svc, "generate_index") as m_index,
    ):
        m_create.return_value = {"name": "KB-uuid"}
        m_upload.return_value = []
        m_index.return_value = None

        svc.setup_from_directory(
            "KB",
            "./dir",
            wait_for_index=False,
            index_timeout=42,
        )

    m_index.assert_called_once_with("KB-uuid", wait=False, timeout=42)
