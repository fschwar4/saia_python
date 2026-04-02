"""Voice AI service — transcription and translation."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .exceptions import raise_for_status

if TYPE_CHECKING:
    import requests


class VoiceService:
    """Access the ``/audio/transcriptions`` and ``/audio/translations`` endpoints.

    Args:
        session: A :class:`requests.Session` with auth headers configured.
        base_url: The SAIA API base URL.
    """

    def __init__(self, session: requests.Session, base_url: str):
        self._session = session
        self._base_url = base_url.rstrip("/")

    def transcribe(
        self,
        file_path: str | Path,
        *,
        model: str = "whisper-large-v2",
        response_format: str = "text",
        language: Optional[str] = None,
        wait: bool = True,
    ) -> str | None:
        """Transcribe an audio file to text.

        Args:
            file_path: Path to the audio file (WAV, MP3, MP4, FLAC).
            model: Whisper model to use.
            response_format: Output format — ``"text"``, ``"vtt"``, or ``"srt"``.
            language: Optional language hint (e.g. ``"de"``, ``"en"``).
            wait: If ``True`` (default), block until the result is ready.
                If ``False``, submit the request in the background and
                return ``None`` immediately.

        Returns:
            The transcription as a string, or ``None`` if ``wait=False``.
        """
        return self._audio_request(
            "/audio/transcriptions",
            file_path,
            model=model,
            response_format=response_format,
            language=language,
            wait=wait,
        )

    def translate(
        self,
        file_path: str | Path,
        *,
        model: str = "whisper-large-v2",
        response_format: str = "text",
        wait: bool = True,
    ) -> str | None:
        """Translate an audio file to English text.

        Args:
            file_path: Path to the audio file (WAV, MP3, MP4, FLAC).
            model: Whisper model to use.
            response_format: Output format — ``"text"``, ``"vtt"``, or ``"srt"``.
            wait: If ``True`` (default), block until the result is ready.
                If ``False``, submit the request in the background and
                return ``None`` immediately.

        Returns:
            The English translation as a string, or ``None`` if ``wait=False``.
        """
        return self._audio_request(
            "/audio/translations",
            file_path,
            model=model,
            response_format=response_format,
            wait=wait,
        )

    def _audio_request(
        self,
        endpoint: str,
        file_path: str | Path,
        *,
        model: str,
        response_format: str,
        language: Optional[str] = None,
        wait: bool = True,
    ) -> str | None:
        file_path = Path(file_path)

        def _send() -> str:
            data = {"model": model, "response_format": response_format}
            if language:
                data["language"] = language

            with open(file_path, "rb") as f:
                resp = self._session.post(
                    f"{self._base_url}{endpoint}",
                    data=data,
                    files={"file": (file_path.name, f)},
                )
            raise_for_status(resp)

            content_type = resp.headers.get("content-type", "")
            if "json" in content_type:
                body = resp.json()
                if isinstance(body, dict):
                    return body.get("text", resp.text)
                return str(body)
            return resp.text

        if not wait:
            threading.Thread(target=_send, daemon=True).start()
            return None

        return _send()

    def __repr__(self):
        return f"VoiceService(base_url={self._base_url!r})"
