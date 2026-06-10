"""Voice AI service — transcription and translation."""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from ._http import RetryPolicy, coerce_retry, execute, new_session_like, resolve_retry
from .exceptions import raise_for_status

if TYPE_CHECKING:
    import requests


class VoiceService:
    """Access the ``/audio/transcriptions`` and ``/audio/translations`` endpoints.

    Args:
        session: A :class:`requests.Session` with auth headers configured.
        base_url: The SAIA API base URL.
    """

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        *,
        retry: RetryPolicy | bool | None = None,
    ):
        self._session = session
        self._base_url = base_url
        self._retry = coerce_retry(retry)

    def transcribe(
        self,
        file_path: str | Path,
        *,
        model: str = "whisper-large-v2",
        response_format: str = "text",
        language: str | None = None,
        wait: bool = True,
        retry: RetryPolicy | bool | None = None,
    ) -> str | concurrent.futures.Future[str]:
        """Transcribe an audio file to text.

        Args:
            file_path: Path to the audio file (WAV, MP3, MP4, FLAC).
            model: Whisper model to use.
            response_format: Output format — ``"text"``, ``"vtt"``, or ``"srt"``.
            language: Optional language hint (e.g. ``"de"``, ``"en"``).
            wait: If ``True`` (default), block until the transcription is
                ready and return it as a string. If ``False``, submit the
                request on a background thread and return a
                :class:`concurrent.futures.Future` immediately so the call
                does not block. Resolve it with ``.result()`` (which
                re-raises any error), poll with ``.done()``, or attach
                ``.add_done_callback(...)``.

        Returns:
            The transcription string when ``wait=True``; otherwise a
            ``Future`` that resolves to that string.

        Example::

            # Blocking
            text = client.voice.transcribe("meeting.mp3")

            # Non-blocking — kick it off, do other work, collect later
            fut = client.voice.transcribe("meeting.mp3", wait=False)
            ...                       # other work runs while it transcribes
            text = fut.result()       # blocks only now, re-raises on error
        """
        return self._audio_request(
            "/audio/transcriptions",
            file_path,
            model=model,
            response_format=response_format,
            language=language,
            wait=wait,
            retry=retry,
        )

    def translate(
        self,
        file_path: str | Path,
        *,
        model: str = "whisper-large-v2",
        response_format: str = "text",
        wait: bool = True,
        retry: RetryPolicy | bool | None = None,
    ) -> str | concurrent.futures.Future[str]:
        """Translate an audio file to English text.

        Args:
            file_path: Path to the audio file (WAV, MP3, MP4, FLAC).
            model: Whisper model to use.
            response_format: Output format — ``"text"``, ``"vtt"``, or ``"srt"``.
            wait: If ``True`` (default), block until the result is ready and
                return it as a string. If ``False``, submit on a background
                thread and return a :class:`concurrent.futures.Future` that
                resolves to the translation (see :meth:`transcribe`).

        Returns:
            The English translation string when ``wait=True``; otherwise a
            ``Future`` that resolves to that string.
        """
        return self._audio_request(
            "/audio/translations",
            file_path,
            model=model,
            response_format=response_format,
            wait=wait,
            retry=retry,
        )

    def _new_session(self) -> requests.Session:
        """Create a fresh Session mirroring the client's auth headers.

        Backgrounded requests (``wait=False``) use their own Session so they
        never share the client's Session — and its connection pool — across
        threads (``requests.Session`` is not guaranteed thread-safe). Thin
        wrapper around :func:`saia_python._http.new_session_like` so the
        "fresh authed background Session" idiom has a single implementation.
        """
        return new_session_like(self._session)

    def _audio_request(
        self,
        endpoint: str,
        file_path: str | Path,
        *,
        model: str,
        response_format: str,
        language: str | None = None,
        wait: bool = True,
        retry: RetryPolicy | bool | None = None,
    ) -> str | concurrent.futures.Future[str]:
        file_path = Path(file_path)
        policy = resolve_retry(self._retry, retry)

        def _send(session: requests.Session) -> str:
            data = {"model": model, "response_format": response_format}
            if language:
                data["language"] = language

            # Read the file once into bytes so a 429 retry can re-send it — a
            # one-shot file handle would be exhausted after the first attempt.
            file_field = (file_path.name, file_path.read_bytes())
            resp = execute(
                session,
                "post",
                f"{self._base_url}{endpoint}",
                policy=policy,
                idempotent=True,
                data=data,
                files={"file": file_field},
            )
            raise_for_status(resp)

            content_type = resp.headers.get("content-type", "")
            if "json" in content_type:
                body = resp.json()
                if isinstance(body, dict):
                    return body.get("text", resp.text)
                return str(body)
            return resp.text

        if wait:
            return _send(self._session)

        # Non-blocking: run on a worker thread with its OWN Session and hand
        # back a Future. The caller resolves it with .result() (which
        # re-raises any error), polls with .done(), or attaches a callback —
        # so the result is never lost the way a bare fire-and-forget loses it.
        future: concurrent.futures.Future[str] = concurrent.futures.Future()

        def _worker() -> None:
            if not future.set_running_or_notify_cancel():
                return
            session = self._new_session()
            try:
                future.set_result(_send(session))
            except BaseException as exc:  # surfaced to the caller via .result()
                future.set_exception(exc)
            finally:
                session.close()

        threading.Thread(target=_worker, daemon=True).start()
        return future

    def __repr__(self):
        return f"VoiceService(base_url={self._base_url!r})"
