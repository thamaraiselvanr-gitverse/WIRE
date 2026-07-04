"""Additional edge-path coverage: document/image ingestion corners and the
section classifier's ARIA-role heuristics."""

import base64

import pytest

from wire.generation.document_ingestion import DocumentIngestionPipeline as Doc
from wire.generation.image_ingestion import ImageIngestionPipeline as Img
from wire.schema.canonical import ComponentNode
from wire.schema.semantic_schema import SectionRole
from wire.semantic.llm_guard import LLMGuard
from wire.semantic.section_classifier import SectionClassifier


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ── document edges ──
def test_document_base64_error_and_data_uri_and_txt_fallback(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    with pytest.raises(ValueError):
        Doc.decode_and_verify("%%% not base64 %%%")

    uri = "data:text/plain;base64," + _b64(b"hello from data uri")
    out = Doc.process(uri, str(assets), original_filename="note.txt")
    assert "hello from data uri" in out["extracted_text"]

    # No extension but valid UTF-8 -> treated as text.
    out2 = Doc.process(
        _b64(b"just plain words"), str(assets), original_filename="noext"
    )
    assert out2["ext"] == "txt"


def test_document_content_types():
    assert Doc._content_type("csv") == "text/csv"
    assert Doc._content_type("json") == "application/json"
    assert Doc._content_type("md") == "text/markdown"
    assert "wordprocessing" in Doc._content_type("docx")
    assert Doc._content_type("unknown") == "text/plain"


def test_document_structure_markdown_and_caps_headings():
    s = Doc._structure("# Big Title\n\nIntro paragraph here.\n\nGET IN TOUCH\nemail us")
    assert s["title"] == "Big Title"
    assert any(h in ("Big Title", "GET IN TOUCH") for h in s["headings"])


# ── image edges ──
def test_image_data_uri_oversize_and_bad_magic(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    # Oversize rejected.
    with pytest.raises(ValueError):
        Img.decode_and_verify(_b64(png), max_size_bytes=4)
    # Bad magic bytes rejected.
    with pytest.raises(ValueError):
        Img.decode_and_verify(_b64(b"not-an-image-at-all"))
    # WebP magic accepted by the verifier.
    webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8
    Img._verify_magic_bytes(webp)  # must not raise


def test_image_alt_from_numeric_filename():
    from wire.generation.image_ingestion import _alt_from_filename

    assert _alt_from_filename("12345.png", 10, 10) == "12345"


# ── section classifier ARIA heuristics ──
def _sec(role):
    return ComponentNode(tag="section", attributes={"role": role})


def test_classifier_aria_roles():
    clf = SectionClassifier(LLMGuard())
    root = ComponentNode(
        tag="body",
        children=[
            _sec("navigation"),
            _sec("contentinfo"),
            _sec("banner"),
            _sec("complementary"),
        ],
    )
    roles = [c.section_role for c in clf.classify_tree(root)]
    assert roles == [
        SectionRole.NAVIGATION,
        SectionRole.FOOTER,
        SectionRole.HERO,
        SectionRole.SIDEBAR,
    ]
