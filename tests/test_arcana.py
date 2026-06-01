"""Tests for saia_python.arcana — generate_index transport-error handling."""

from unittest.mock import MagicMock

import pytest
import requests

from saia_python.arcana import ArcanaService
from saia_python.exceptions import APIError


def _make_service() -> ArcanaService:
    """Build an ArcanaService with a mocked session (no real HTTP)."""
    svc = ArcanaService.__new__(ArcanaService)
    svc._session = MagicMock()
    svc._session.headers = {}  # real dict so new_session_like(...).headers.update works
    svc._base_url = "https://example.com/v1"
    svc._arcana_base = "https://example.com/v1/arcanas/api/v1"
    svc._api_key = "test"
    svc._timeout = (10.0, 60.0)
    return svc


def _get_response(status: str) -> MagicMock:
    """Build a `GET /arcana/{name}` response with the given index_status."""
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.json.return_value = {
        "name": "my-arcana",
        "index_info": {"index_status": status},
    }
    return resp


def _http_error_response(status_code: int, text: str) -> MagicMock:
    """Build a non-OK HTTP response (e.g. 500, 504)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = False
    resp.text = text
    resp.headers = {}
    resp.json.side_effect = ValueError("no json body")
    return resp


class TestGenerateIndexTransportErrors:
    """The trigger POST commonly drops mid-flight — verify the poll loop kicks in."""

    def test_connection_error_falls_through_to_poll(self):
        """RemoteDisconnected wrapped in ConnectionError → sanity GET + poll to terminal."""
        svc = _make_service()
        svc._session.post.side_effect = requests.exceptions.ConnectionError(
            "('Connection aborted.', RemoteDisconnected("
            "'Remote end closed connection without response'))"
        )
        svc._session.get.side_effect = [
            _get_response("PENDING"),  # sanity check after POST
            _get_response("PENDING"),  # first poll iteration
            _get_response("INDEXED"),  # second poll iteration → terminal
        ]
        result = svc.generate_index(
            "my-arcana",
            poll_interval=0,
            timeout=10,
        )
        assert result["index_info"]["index_status"] == "INDEXED"
        assert svc._session.get.call_count == 3

    def test_read_timeout_falls_through_to_poll(self):
        """requests.exceptions.ReadTimeout → sanity GET + poll to terminal."""
        svc = _make_service()
        svc._session.post.side_effect = requests.exceptions.ReadTimeout(
            "HTTPConnectionPool: Read timed out."
        )
        svc._session.get.side_effect = [
            _get_response("PENDING"),
            _get_response("INDEXED"),
        ]
        result = svc.generate_index(
            "my-arcana",
            poll_interval=0,
            timeout=10,
        )
        assert result["index_info"]["index_status"] == "INDEXED"

    def test_504_gateway_timeout_falls_through_to_poll(self):
        """APIError(504) from nginx → poll to terminal (no sanity check needed)."""
        svc = _make_service()
        svc._session.post.return_value = _http_error_response(
            504, "504 Gateway Timeout"
        )
        svc._session.get.side_effect = [
            _get_response("PENDING"),
            _get_response("INDEXED"),
        ]
        result = svc.generate_index(
            "my-arcana",
            poll_interval=0,
            timeout=10,
        )
        assert result["index_info"]["index_status"] == "INDEXED"
        assert svc._session.get.call_count == 2

    def test_real_connection_error_propagates(self):
        """Server genuinely down: sanity GET also fails → original error propagates."""
        svc = _make_service()
        svc._session.post.side_effect = requests.exceptions.ConnectionError(
            "Connection aborted."
        )
        svc._session.get.side_effect = requests.exceptions.ConnectionError(
            "Connection refused — server is down"
        )
        with pytest.raises(requests.exceptions.ConnectionError):
            svc.generate_index("my-arcana", poll_interval=0, timeout=10)

    def test_non_504_api_error_propagates(self):
        """500 Internal Server Error is a real failure — no polling, raises immediately."""
        svc = _make_service()
        svc._session.post.return_value = _http_error_response(
            500, "500 Internal Server Error"
        )
        with pytest.raises(APIError) as exc_info:
            svc.generate_index("my-arcana", poll_interval=0, timeout=10)
        assert exc_info.value.status_code == 500
        assert svc._session.get.call_count == 0

    def test_successful_post_polls_to_terminal(self):
        """Happy path: POST returns 200 → poll to terminal."""
        svc = _make_service()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.ok = True
        svc._session.post.return_value = post_resp
        svc._session.get.side_effect = [
            _get_response("PENDING"),
            _get_response("INDEXED"),
        ]
        result = svc.generate_index(
            "my-arcana",
            poll_interval=0,
            timeout=10,
        )
        assert result["index_info"]["index_status"] == "INDEXED"

    def test_timeout_raised_when_indexing_never_completes(self):
        """If status never reaches terminal, TimeoutError after `timeout` seconds."""
        svc = _make_service()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.ok = True
        svc._session.post.return_value = post_resp
        # Always return PENDING — never terminal
        svc._session.get.return_value = _get_response("PENDING")
        with pytest.raises(TimeoutError, match="did not complete"):
            svc.generate_index("my-arcana", poll_interval=0, timeout=0)

    def test_transient_poll_timeout_is_tolerated(self):
        """A dropped/slow individual poll GET must not abort a still-building
        reindex — retry on the next poll, bounded by the overall timeout."""
        svc = _make_service()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.ok = True
        svc._session.post.return_value = post_resp
        svc._session.get.side_effect = [
            requests.exceptions.ReadTimeout("transient poll blip"),  # tolerated
            _get_response("PENDING"),
            _get_response("INDEXED"),
        ]
        result = svc.generate_index("my-arcana", poll_interval=0, timeout=10)
        assert result["index_info"]["index_status"] == "INDEXED"
        assert svc._session.get.call_count == 3

    def test_persistent_poll_timeout_reports_last_error(self):
        """If polls keep timing out until the deadline, the TimeoutError surfaces
        the transport error instead of a misleading empty 'Last status'."""
        svc = _make_service()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.ok = True
        svc._session.post.return_value = post_resp
        svc._session.get.side_effect = requests.exceptions.ReadTimeout(
            "poll read timed out"
        )
        with pytest.raises(TimeoutError) as exc_info:
            svc.generate_index("my-arcana", poll_interval=0.01, timeout=0.05)
        msg = str(exc_info.value)
        assert "did not complete" in msg
        assert "poll read timed out" in msg  # the transport error is surfaced
        assert "Last status" not in msg  # never got a successful status read


def test_generate_index_wait_false_uses_dedicated_session(monkeypatch):
    """wait=False fires the trigger on its OWN Session (not the shared one)
    and closes it, so it never races the caller's polling get()s."""
    import threading

    svc = _make_service()
    created_sessions = []

    class _FakeSession:
        def __init__(self):
            created_sessions.append(self)
            self.headers = {}
            self.posted = False
            self.closed = False

        def post(self, *args, **kwargs):
            self.posted = True
            resp = MagicMock()
            resp.status_code = 200
            resp.ok = True
            return resp

        def close(self):
            self.closed = True

    class _SyncThread:
        """Run the worker synchronously so the test is deterministic."""

        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(requests, "Session", _FakeSession)
    monkeypatch.setattr(threading, "Thread", _SyncThread)

    result = svc.generate_index("my-arcana", wait=False)

    assert result is None
    assert len(created_sessions) == 1
    assert created_sessions[0].posted is True
    assert created_sessions[0].closed is True
    # The shared client Session was NOT used for the background trigger.
    svc._session.post.assert_not_called()


def _ok_response() -> MagicMock:
    """A successful upload/delete response (200, small JSON body)."""
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.headers = {}
    resp.json.return_value = {"status": "ok"}
    return resp


class TestUploadFiles:
    """ArcanaService.upload_files — upload an explicit, caller-chosen list."""

    def test_uploads_explicit_list_with_put_by_default(self, tmp_path):
        svc = _make_service()
        svc._session.put.return_value = _ok_response()
        f1 = tmp_path / "a.txt"
        f1.write_text("a")
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        results = svc.upload_files("my-arcana", [f1, f2])
        assert [r["status"] for r in results] == ["uploaded", "uploaded"]
        assert [r["file"] for r in results] == ["a.txt", "b.txt"]
        assert svc._session.put.call_count == 2
        svc._session.post.assert_not_called()

    def test_overwrite_false_uses_post(self, tmp_path):
        svc = _make_service()
        svc._session.post.return_value = _ok_response()
        f1 = tmp_path / "a.txt"
        f1.write_text("a")
        results = svc.upload_files("my-arcana", [f1], overwrite=False)
        assert results[0]["status"] == "uploaded"
        assert svc._session.post.call_count == 1
        svc._session.put.assert_not_called()

    def test_missing_file_recorded_as_failed(self, tmp_path):
        svc = _make_service()
        svc._session.put.return_value = _ok_response()
        results = svc.upload_files("my-arcana", [tmp_path / "nope.txt"])
        assert results[0]["status"] == "failed"
        assert "error" in results[0]


class TestSyncDirectory:
    """ArcanaService.sync_directory — caller-defined select() policy."""

    def test_classifies_and_indexes_once(self, tmp_path):
        svc = _make_service()
        (tmp_path / "new.txt").write_text("n")
        (tmp_path / "changed.txt").write_text("c")
        (tmp_path / "same.txt").write_text("s")
        svc.list_files = MagicMock(
            return_value=[
                {"name": "changed.txt"},
                {"name": "same.txt"},
                {"name": "orphan.txt"},
            ]
        )
        svc.upload = MagicMock(return_value={"status": "ok"})
        svc.delete_file = MagicMock(return_value=None)
        svc.generate_index = MagicMock(
            return_value={"index_info": {"index_status": "INDEXED"}}
        )

        def select(path, remote):
            if remote is None:
                return "upload"
            return "replace" if path.name == "changed.txt" else "skip"

        report = svc.sync_directory("my-arcana", tmp_path, select=select, prune=True)

        assert set(report["uploaded"]) == {"new.txt"}
        assert set(report["replaced"]) == {"changed.txt"}
        assert set(report["skipped"]) == {"same.txt"}
        assert set(report["deleted"]) == {"orphan.txt"}
        assert report["index"] == {"index_info": {"index_status": "INDEXED"}}
        overwrite_by_file = {
            c.args[1].name: c.kwargs.get("overwrite") for c in svc.upload.call_args_list
        }
        assert overwrite_by_file == {"new.txt": False, "changed.txt": True}
        svc.delete_file.assert_called_once_with("my-arcana", "orphan.txt")
        svc.generate_index.assert_called_once()

    def test_no_changes_skips_index(self, tmp_path):
        svc = _make_service()
        (tmp_path / "a.txt").write_text("a")
        svc.list_files = MagicMock(return_value=[{"name": "a.txt"}])
        svc.upload = MagicMock()
        svc.generate_index = MagicMock()
        report = svc.sync_directory("my-arcana", tmp_path, select=lambda p, r: "skip")
        assert report["skipped"] == ["a.txt"]
        svc.upload.assert_not_called()
        svc.generate_index.assert_not_called()

    def test_index_false_suppresses_indexing(self, tmp_path):
        svc = _make_service()
        (tmp_path / "a.txt").write_text("a")
        svc.list_files = MagicMock(return_value=[])
        svc.upload = MagicMock(return_value={"status": "ok"})
        svc.generate_index = MagicMock()
        report = svc.sync_directory(
            "my-arcana", tmp_path, select=lambda p, r: "upload", index=False
        )
        assert report["uploaded"] == ["a.txt"]
        svc.generate_index.assert_not_called()

    def test_prune_false_keeps_orphans(self, tmp_path):
        svc = _make_service()
        (tmp_path / "a.txt").write_text("a")
        svc.list_files = MagicMock(return_value=[{"name": "orphan.txt"}])
        svc.upload = MagicMock(return_value={"status": "ok"})
        svc.delete_file = MagicMock()
        svc.generate_index = MagicMock(return_value=None)
        report = svc.sync_directory("my-arcana", tmp_path, select=lambda p, r: "upload")
        assert report["deleted"] == []
        svc.delete_file.assert_not_called()

    def test_bad_select_return_raises(self, tmp_path):
        svc = _make_service()
        (tmp_path / "a.txt").write_text("a")
        svc.list_files = MagicMock(return_value=[])
        with pytest.raises(ValueError, match="select"):
            svc.sync_directory("my-arcana", tmp_path, select=lambda p, r: "bogus")


class TestDefaultTimeout:
    """Every ARCANA control-plane call must carry a timeout so a server that
    accepts a request but never responds raises instead of hanging forever
    (``requests.Session`` has no native default timeout)."""

    def test_default_timeout_injected_when_unset(self):
        svc = _make_service()
        svc._session.delete.return_value = _ok_response()
        svc.delete_file("my-arcana", "f.txt")
        assert svc._session.delete.call_args.kwargs["timeout"] == (10.0, 60.0)

    def test_explicit_call_timeout_is_preserved(self):
        # heartbeat passes its own timeout=10; the default must not clobber it.
        svc = _make_service()
        resp = MagicMock()
        resp.status_code = 204
        svc._session.get.return_value = resp
        assert svc.heartbeat() is True
        assert svc._session.get.call_args.kwargs["timeout"] == 10

    def test_configured_timeout_is_used(self):
        svc = _make_service()
        svc._timeout = (3.0, 12.0)
        svc._session.get.return_value = _ok_response()
        svc.list_files("my-arcana")
        assert svc._session.get.call_args.kwargs["timeout"] == (3.0, 12.0)

    def test_timeout_propagates_from_single_call(self):
        """A single-file method does not swallow the timeout — it propagates."""
        svc = _make_service()
        svc._session.delete.side_effect = requests.exceptions.ReadTimeout(
            "read timed out"
        )
        with pytest.raises(requests.exceptions.ReadTimeout):
            svc.delete_file("my-arcana", "f.txt")

    def test_batch_records_timeout_per_file_and_continues(self, tmp_path):
        """In a batch, a per-file timeout is recorded and the loop carries on —
        it neither hangs nor aborts the whole batch (the reported repro)."""
        svc = _make_service()
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        svc._session.delete.side_effect = [
            requests.exceptions.ReadTimeout("read timed out"),
            _ok_response(),
        ]
        results = svc.delete_directory("my-arcana", tmp_path)
        by_file = {r["file"]: r["status"] for r in results}
        assert by_file == {"a.txt": "failed", "b.txt": "deleted"}
        failed = next(r for r in results if r["status"] == "failed")
        assert "read timed out" in failed["error"]


class TestOnResultHook:
    """The per-file callback lets callers record provenance / transaction logs
    without reimplementing the upload loop (downstream consumer feedback)."""

    def test_upload_files_invokes_on_result_per_file_in_order(self, tmp_path):
        svc = _make_service()
        svc._session.put.return_value = _ok_response()
        f1 = tmp_path / "a.txt"
        f1.write_text("a")
        f2 = tmp_path / "b.txt"
        f2.write_text("b")
        seen = []
        svc.upload_files(
            "kb", [f1, f2], on_result=lambda p, e: seen.append((p, e["status"]))
        )
        assert seen == [(f1, "uploaded"), (f2, "uploaded")]

    def test_on_result_reports_failure_with_error(self, tmp_path):
        svc = _make_service()
        svc._session.put.return_value = _ok_response()
        seen = []
        svc.upload_files(
            "kb", [tmp_path / "missing.txt"], on_result=lambda p, e: seen.append(e)
        )
        assert seen[0]["status"] == "failed"
        assert "error" in seen[0]

    def test_sync_directory_invokes_on_result_for_local_files(self, tmp_path):
        svc = _make_service()
        (tmp_path / "new.txt").write_text("n")
        (tmp_path / "keep.txt").write_text("k")
        svc.list_files = MagicMock(return_value=[{"name": "keep.txt"}])
        svc.upload = MagicMock(return_value={"status": "ok"})
        svc.generate_index = MagicMock(return_value=None)
        seen = {}

        def select(path, remote):
            return "upload" if remote is None else "skip"

        svc.sync_directory(
            "kb",
            tmp_path,
            select=select,
            on_result=lambda p, e: seen.__setitem__(p.name, e["status"]),
        )
        assert seen == {"new.txt": "uploaded", "keep.txt": "skipped"}
