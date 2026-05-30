"""Document conversion service (Docling) — convert PDFs and documents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .exceptions import raise_for_status

if TYPE_CHECKING:
    import requests


@dataclass
class ConversionResult:
    """Result of a document conversion via the Docling service.

    Attributes:
        filename: The original document filename.
        response_type: The output format (``markdown``, ``html``, ``json``, or ``tokens``).
        content: The converted content as a string.
        images: A list of extracted image dicts, each with ``type``,
            ``filename``, and ``data`` (base64-encoded) keys.
    """

    filename: str
    response_type: str
    content: str
    images: list[dict] = field(default_factory=list)

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
        extract_tables_as_images: Optional[bool] = None,
        image_resolution_scale: Optional[int] = None,
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
            images=data.get("images", []),
        )

    def convert_to_markdown(
        self, file_path: str | Path, **kwargs
    ) -> str:
        """Convert a document to markdown (convenience method).

        Args:
            file_path: Path to the document file.
            **kwargs: Additional parameters passed to :meth:`convert`.

        Returns:
            The markdown content as a string.
        """
        return self.convert(file_path, response_type="markdown", **kwargs).content

    def convert_to_html(
        self, file_path: str | Path, **kwargs
    ) -> str:
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
