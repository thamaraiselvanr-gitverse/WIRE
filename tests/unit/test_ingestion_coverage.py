"""Edge-path coverage for media and document ingestion (format detection,
error handling, content types) — all offline."""

import base64
import io
import zipfile

import pytest

from wire.generation.document_ingestion import DocumentIngestionPipeline
from wire.generation.media_ingestion import MediaIngestionPipeline


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ── media ──
def test_media_video_mp4_and_audio_mp3(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
    out = MediaIngestionPipeline.process(_b64(mp4), str(assets), kind="video")
    assert out["kind"] == "video" and out["content_type"] == "video/mp4"

    mp3 = b"ID3\x03\x00" + b"\x00" * 16
    outa = MediaIngestionPipeline.process(_b64(mp3), str(assets), kind="audio")
    assert outa["content_type"] == "audio/mpeg"


def test_media_webm_and_wav_and_ogg_flac(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 20
    assert (
        MediaIngestionPipeline.process(_b64(webm), str(assets), kind="video")[
            "content_type"
        ]
        == "video/webm"
    )
    wav = b"RIFF\x00\x00\x00\x00WAVEfmt "
    assert MediaIngestionPipeline._detect_format(wav, "audio") == "wav"
    assert (
        MediaIngestionPipeline._detect_format(b"OggS" + b"\x00" * 8, "audio") == "ogg"
    )
    assert (
        MediaIngestionPipeline._detect_format(b"fLaC" + b"\x00" * 8, "audio") == "flac"
    )


def test_media_bad_kind_and_unrecognized_and_oversize(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    with pytest.raises(ValueError):
        MediaIngestionPipeline.process(_b64(b"x" * 20), str(assets), kind="hologram")
    with pytest.raises(ValueError):  # not a recognized video
        MediaIngestionPipeline.process(
            _b64(b"garbagebytes!"), str(assets), kind="video"
        )
    with pytest.raises(ValueError):  # oversize
        MediaIngestionPipeline.process(
            _b64(b"\x1a\x45\xdf\xa3" + b"\x00" * 100),
            str(assets),
            kind="video",
            max_size_bytes=10,
        )


def test_media_data_uri_prefix_stripped(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 20
    uri = "data:video/webm;base64," + _b64(webm)
    out = MediaIngestionPipeline.process(uri, str(assets), kind="video")
    assert out["content_type"] == "video/webm"


# ── documents ──
def _docx_bytes(paragraphs) -> bytes:
    buf = io.BytesIO()
    body = "".join(f"<w:p><w:t>{p}</w:t></w:p>" for p in paragraphs)
    doc = f'<?xml version="1.0"?><w:document><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def test_document_docx_extraction(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    out = DocumentIngestionPipeline.process(
        _b64(_docx_bytes(["Hello world", "Second line"])),
        str(assets),
        original_filename="resume.docx",
    )
    assert out["ext"] == "docx"
    assert "Hello world" in out["extracted_text"]
    assert "wordprocessing" in out["content_type"]


def test_document_html_tag_stripping_and_content_type(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    html = b"<html><body><h1>Title</h1><p>Body text</p></body></html>"
    out = DocumentIngestionPipeline.process(
        _b64(html), str(assets), original_filename="page.html"
    )
    assert out["ext"] == "html"
    assert "Title" in out["extracted_text"] and "<h1>" not in out["extracted_text"]
    assert out["content_type"] == "text/html"


def test_document_unsupported_and_empty_and_oversize(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    with pytest.raises(ValueError):  # empty
        DocumentIngestionPipeline.process(_b64(b""), str(assets))
    with pytest.raises(ValueError):  # binary, no recognized format, no text ext
        DocumentIngestionPipeline.process(
            _b64(b"\xff\xfe\x00\x01\x02binary"), str(assets), original_filename="x.bin"
        )
    with pytest.raises(ValueError):  # oversize
        DocumentIngestionPipeline.process(
            _b64(b"hello world"), str(assets), max_size_bytes=3
        )


def test_document_pdf_without_pypdf_stores_without_text(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    # Force the optional pypdf import to fail so the stored-without-text path runs.
    import builtins

    real_import = builtins.__import__

    def _no_pypdf(name, *a, **k):
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_pypdf)
    pdf = b"%PDF-1.4\n%stub\n"
    out = DocumentIngestionPipeline.process(
        _b64(pdf), str(assets), original_filename="doc.pdf"
    )
    assert out["ext"] == "pdf"
    assert out["extracted_text"] == ""
    assert out["content_type"] == "application/pdf"
