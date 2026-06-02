"""Document conversion service (Docling) — convert PDFs and documents."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .exceptions import raise_for_status

if TYPE_CHECKING:
    import requests

# The Docling API returns each image's base64 payload under "image"; "data"
# and "content" are accepted as fallbacks for robustness across API versions.
_IMAGE_KEYS = ("image", "data", "content")


@dataclass
class ConversionImage:
    """A single image extracted during a document conversion.

    Attributes:
        filename: Suggested file name, e.g. ``picture-1.png``.
        data: The decoded image bytes (ready to write to disk).
        type: The image kind reported by the API, e.g. ``picture``.
    """

    filename: str
    data: bytes
    type: str = ""

    @classmethod
    def from_api(cls, raw: dict, index: int = 0) -> ConversionImage:
        """Build from a raw API image dict, normalising key and encoding.

        The base64 payload is taken from ``image`` (falling back to
        ``data``/``content``), any ``data:`` URI prefix is stripped, and the
        result is decoded to bytes once, here at the API boundary.
        """
        blob = next((raw[k] for k in _IMAGE_KEYS if raw.get(k)), "")
        if isinstance(blob, str) and blob.startswith("data:") and "," in blob:
            blob = blob.split(",", 1)[1]
        return cls(
            filename=raw.get("filename") or f"image-{index + 1}.png",
            data=base64.b64decode(blob) if blob else b"",
            type=raw.get("type", ""),
        )


@dataclass
class ConversionResult:
    """Result of a document conversion via the Docling service.

    Attributes:
        filename: The original document filename.
        response_type: The output format (``markdown``, ``html``, ``json``, or ``tokens``).
        content: The converted content as a string.
        images: The extracted images as :class:`ConversionImage` objects
            (decoded ``bytes`` + ``filename``). Use :meth:`save_images` or
            :meth:`save_all` to write them to disk.
    """

    filename: str
    response_type: str
    content: str
    images: list[ConversionImage] = field(default_factory=list)

    def save(self, path: str | Path) -> Path:
        """Save the converted content to a file.

        Args:
            path: Output file path.

        Returns:
            The path written to.
        """
        path = Path(path)
        path.write_text(self.content, encoding="utf-8")
        return path

    def save_images(self, directory: str | Path) -> list[Path]:
        """Write every extracted image into ``directory``.

        Each :class:`ConversionImage` is written under its ``filename``;
        decoding already happened at parse time.

        Args:
            directory: Target directory (created if missing).

        Returns:
            The list of written image paths (empty if there are no images).
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for i, img in enumerate(self.images, start=1):
            out_path = directory / (img.filename or f"image-{i}.png")
            out_path.write_bytes(img.data)
            written.append(out_path)
        return written

    def save_all(self, directory: str | Path, *, stem: str | None = None) -> list[Path]:
        """Save the content file *and* all images into ``directory``.

        The content is written as ``<stem>.<ext>`` where ``ext`` is inferred
        from :attr:`response_type` (``markdown`` → ``md``) and ``stem`` defaults
        to the source :attr:`filename` stem. Images are written via
        :meth:`save_images`, so any ``picture-N.png`` links in the content
        resolve next to it.

        Args:
            directory: Target directory (created if missing).
            stem: Optional base name for the content file.

        Returns:
            All written paths, content file first.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        ext = {"markdown": "md", "html": "html", "json": "json", "tokens": "txt"}.get(
            self.response_type, "txt"
        )
        content_path = directory / f"{stem or Path(self.filename).stem}.{ext}"
        content_path.write_text(self.content, encoding="utf-8")
        return [content_path, *self.save_images(directory)]

    def __str__(self):
        n_img = len(self.images)
        preview = self.content[:200]
        suffix = "..." if len(self.content) > 200 else ""
        return (
            f"ConversionResult({self.filename!r}, {self.response_type}, "
            f"{n_img} images, {len(self.content)} chars)\n{preview}{suffix}"
        )


class DocumentService:
    """Access the ``/documents/convert`` endpoint (Docling).

    Converts PDF and other document formats to markdown, HTML, JSON,
    or token representations.

    Args:
        session: A :class:`requests.Session` with auth headers configured.
        base_url: The SAIA API base URL.
    """

    def __init__(self, session: requests.Session, base_url: str):
        self._session = session
        self._base_url = base_url

    def convert(
        self,
        file_path: str | Path,
        *,
        response_type: str = "markdown",
        extract_tables_as_images: bool | None = None,
        image_resolution_scale: int | None = None,
    ) -> ConversionResult:
        """Convert a document using the Docling service.

        Args:
            file_path: Path to the document file (PDF, etc.).
            response_type: Output format — ``"markdown"`` (default),
                ``"html"``, ``"json"``, or ``"tokens"``.
            extract_tables_as_images: If ``True``, render tables as images
                instead of structured text.
            image_resolution_scale: Image quality multiplier (1–4).

        Returns:
            A :class:`ConversionResult` with the converted content and
            any extracted images.
        """
        file_path = Path(file_path)
        params: dict = {"response_type": response_type}
        if extract_tables_as_images is not None:
            params["extract_tables_as_images"] = str(extract_tables_as_images).lower()
        if image_resolution_scale is not None:
            params["image_resolution_scale"] = image_resolution_scale

        with open(file_path, "rb") as f:
            resp = self._session.post(
                f"{self._base_url}/documents/convert",
                params=params,
                files={"document": (file_path.name, f)},
            )
        raise_for_status(resp)
        data = resp.json()

        content = data.get(response_type, data.get("markdown", ""))
        if isinstance(content, (list, dict)):
            content = json.dumps(content, indent=2)

        return ConversionResult(
            filename=data.get("filename", file_path.name),
            response_type=data.get("response_type", response_type),
            content=content,
            images=[
                ConversionImage.from_api(img, i)
                for i, img in enumerate(data.get("images", []))
            ],
        )

    def convert_to_markdown(self, file_path: str | Path, **kwargs) -> str:
        """Convert a document to markdown (convenience method).

        Args:
            file_path: Path to the document file.
            **kwargs: Additional parameters passed to :meth:`convert`.

        Returns:
            The markdown content as a string.
        """
        return self.convert(file_path, response_type="markdown", **kwargs).content

    def convert_to_html(self, file_path: str | Path, **kwargs) -> str:
        """Convert a document to HTML (convenience method).

        Args:
            file_path: Path to the document file.
            **kwargs: Additional parameters passed to :meth:`convert`.

        Returns:
            The HTML content as a string.
        """
        return self.convert(file_path, response_type="html", **kwargs).content

    def __repr__(self):
        return f"DocumentService(base_url={self._base_url!r})"
