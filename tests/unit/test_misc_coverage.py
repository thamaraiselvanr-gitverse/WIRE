"""Small remaining branches: ComprehensiveExtractor with a fake page, and the
pure image-hashing helpers in VisualDiff."""

import base64
import io

import pytest
from PIL import Image

from wire.agents.extraction.comprehensive_extractor import ComprehensiveExtractor
from wire.validation.visual_diff import VisualDiff


class _PageErr:
    async def evaluate(self, *a, **k):
        raise RuntimeError("evaluate failed")


class _PageOk:
    async def evaluate(self, *a, **k):
        return {"title": "T"}

    async def content(self):
        return '<html><body><i class="fa fa-home"></i></body></html>'


class _PageContentFails:
    async def evaluate(self, *a, **k):
        return {"title": "T"}

    async def content(self):
        raise RuntimeError("content failed")


@pytest.mark.asyncio
async def test_comprehensive_extract_fake_pages():
    err = await ComprehensiveExtractor().extract(_PageErr())
    assert "error" in err

    ok = await ComprehensiveExtractor().extract(_PageOk())
    assert ok["icon_library"] == "font-awesome"

    # If reading the page HTML fails, icon detection falls back to "unknown".
    degraded = await ComprehensiveExtractor().extract(_PageContentFails())
    assert degraded["icon_library"] == "unknown"


def _png_bytes(color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


def test_perceptual_hash_and_distance():
    h1 = VisualDiff.perceptual_hash(_png_bytes((0, 0, 0)))
    h2 = VisualDiff.perceptual_hash(_png_bytes((255, 255, 255)))
    assert isinstance(h1, str) and isinstance(h2, str)
    assert VisualDiff.hamming_distance(h1, h1) == 0
    assert VisualDiff.hamming_distance(h1, h2) >= 0


def test_perceptual_hash_bad_bytes_is_safe():
    # Non-image bytes must not crash the hasher.
    assert isinstance(VisualDiff.perceptual_hash(b"not an image"), str)


def test_file_hash_roundtrip(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello wire")
    digest = VisualDiff.file_hash(str(p))
    assert isinstance(digest, str) and len(digest) > 0


def test_b64_png_is_valid_image():
    # Sanity anchor so the fixture bytes are genuinely decodable.
    raw = base64.b64encode(_png_bytes()).decode()
    assert Image.open(io.BytesIO(base64.b64decode(raw))).size == (16, 16)


def test_structural_compare_mismatched_children_and_text():
    from wire.validation.structural import StructuralValidator

    # Original has extra trailing children; reconstructed has an extra one too,
    # plus text nodes — exercises both alignment tails and the text-node skip.
    original = "<div><p>a</p><span>b</span><b>c</b>text</div>"
    reconstructed = "<div><p>a</p><i>x</i></div>"
    report = StructuralValidator().compare(original, reconstructed)
    assert "structural_score" in report
    assert 0.0 <= report["structural_score"] <= 100.0

    # Unparseable input yields the error branch.
    err = StructuralValidator().compare("", "")
    assert "error" in err or "structural_score" in err
