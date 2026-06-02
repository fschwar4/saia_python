"""Tests for saia_python.documents — image normalisation + save helpers.

Locks the contract that the Docling ``/documents/convert`` API payload (base64
under the ``image`` key) is normalised into typed :class:`ConversionImage`
objects with decoded ``bytes``, and that the save helpers write them correctly.
"""

import base64
from unittest.mock import MagicMock

from saia_python.documents import ConversionImage, ConversionResult, DocumentService

# A tiny byte blob; we only care about base64 round-tripping, not real PNG-ness.
IMG_BYTES = b"\x89PNG\r\n\x1a\n_fake_image_payload_"
IMG_B64 = base64.b64encode(IMG_BYTES).decode()


def _make_service() -> DocumentService:
    """Build a DocumentService with a mocked session (no real HTTP)."""
    svc = DocumentService.__new__(DocumentService)
    svc._session = MagicMock()
    svc._base_url = "https://example.com/v1"
    return svc


def _json_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = payload
    return resp


def test_convert_normalises_images_to_decoded_bytes(tmp_path):
    """convert() reads the API ``image`` key and decodes it into bytes."""
    svc = _make_service()
    svc._session.post.return_value = _json_response(
        {
            "filename": "doc.pdf",
            "response_type": "markdown",
            "markdown": "# Title\n\npicture-1.png",
            "images": [
                {"type": "picture", "filename": "picture-1.png", "image": IMG_B64}
            ],
        }
    )
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4")

    res = svc.convert(src)

    assert res.content.startswith("# Title")
    assert len(res.images) == 1
    img = res.images[0]
    assert isinstance(img, ConversionImage)
    assert img.filename == "picture-1.png"
    assert img.type == "picture"
    assert img.data == IMG_BYTES  # base64 decoded at the boundary


def test_from_api_accepts_data_fallback_and_data_uri():
    """from_api() falls back to a legacy ``data`` key and strips data: URIs."""
    a = ConversionImage.from_api({"filename": "a.png", "data": IMG_B64})
    b = ConversionImage.from_api(
        {"filename": "b.png", "image": "data:image/png;base64," + IMG_B64}
    )
    assert a.data == IMG_BYTES and a.filename == "a.png"
    assert b.data == IMG_BYTES and b.filename == "b.png"


def test_from_api_synthesises_filename_when_missing():
    img = ConversionImage.from_api({"image": IMG_B64}, index=4)
    assert img.filename == "image-5.png"
    assert img.data == IMG_BYTES


def test_save_images_writes_bytes(tmp_path):
    res = ConversionResult(
        filename="doc.pdf",
        response_type="markdown",
        content="x",
        images=[ConversionImage("picture-1.png", IMG_BYTES, "picture")],
    )

    written = res.save_images(tmp_path / "imgs")

    assert [p.name for p in written] == ["picture-1.png"]
    assert written[0].read_bytes() == IMG_BYTES


def test_save_all_writes_content_and_images(tmp_path):
    res = ConversionResult(
        filename="report.pdf",
        response_type="markdown",
        content="# hi",
        images=[ConversionImage("picture-1.png", IMG_BYTES)],
    )

    written = res.save_all(tmp_path / "o")

    assert written[0].name == "report.md"  # extension inferred from response_type
    assert written[0].read_text() == "# hi"
    assert (tmp_path / "o" / "picture-1.png").read_bytes() == IMG_BYTES


def test_convert_to_markdown_returns_string(tmp_path):
    svc = _make_service()
    svc._session.post.return_value = _json_response({"markdown": "# md", "images": []})
    src = tmp_path / "d.pdf"
    src.write_bytes(b"%PDF")

    assert svc.convert_to_markdown(src) == "# md"
