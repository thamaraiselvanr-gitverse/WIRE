import base64
import io
import os
import tempfile
import zipfile

import pytest

from wire.generation.document_ingestion import DocumentIngestionPipeline


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _make_docx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r>"
            f"</w:p></w:body></w:document>",
        )
    return buf.getvalue()


def _ingest(data: bytes, filename: str = ""):
    d = tempfile.mkdtemp()
    assets = os.path.join(d, "assets")
    os.makedirs(assets)
    res = DocumentIngestionPipeline.process(
        _b64(data), assets, original_filename=filename
    )
    return d, res


def test_txt_extracted_directly():
    d, res = _ingest(b"Hello resume content", "cv.txt")
    assert res["ext"] == "txt"
    assert "Hello resume content" in res["extracted_text"]
    assert os.path.exists(os.path.join(d, res["stored_path"]))
    # Sidecar text file is written next to the stored document.
    assert os.path.exists(os.path.join(d, res["stored_path"] + ".txt"))


def test_html_tags_stripped():
    d, res = _ingest(b"<h1>Title</h1><p>Body text</p>", "page.html")
    assert res["ext"] == "html"
    assert "Title" in res["extracted_text"]
    assert "Body text" in res["extracted_text"]
    assert "<h1>" not in res["extracted_text"]


def test_docx_text_extracted_via_stdlib():
    d, res = _ingest(_make_docx("About me paragraph"), "profile.docx")
    assert res["ext"] == "docx"
    assert "About me paragraph" in res["extracted_text"]
    assert res["content_type"].endswith("wordprocessingml.document")


def test_pdf_detected_and_stored():
    # Minimal PDF header; text extraction may be empty without pypdf, but the
    # file must still be detected and stored.
    pdf = b"%PDF-1.4\n%stub\n"
    d, res = _ingest(pdf, "doc.pdf")
    assert res["ext"] == "pdf"
    assert os.path.exists(os.path.join(d, res["stored_path"]))


def test_unsupported_binary_rejected():
    with pytest.raises(ValueError, match="Unsupported document format"):
        _ingest(b"\x00\x01\x02\x03\xff\xfe", "mystery.bin")


def test_oversize_rejected():
    d = tempfile.mkdtemp()
    assets = os.path.join(d, "assets")
    os.makedirs(assets)
    with pytest.raises(ValueError, match="exceeds the limit"):
        DocumentIngestionPipeline.process(
            _b64(b"x" * 100), assets, original_filename="big.txt", max_size_bytes=10
        )
