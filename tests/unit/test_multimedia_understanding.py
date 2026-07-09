"""Understanding derived from ingested multimedia inputs.

The pipelines don't just store/sanitize uploads — they extract enough
understanding to feed accurate substitution: an alt suggestion, dominant
colour, and orientation for images; a title/headings/summary/emails/urls
structure for documents. All offline.
"""

import base64
import io

from PIL import Image

from wire.generation.document_ingestion import DocumentIngestionPipeline
from wire.generation.image_ingestion import ImageIngestionPipeline, _alt_from_filename


def _png_b64(color: tuple, size: tuple) -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_image_understanding_dominant_color_and_orientation(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    # A solid teal, wide image.
    b64 = _png_b64((0, 128, 128), (400, 200))
    out = ImageIngestionPipeline.process(
        b64, str(assets), original_filename="hero-banner.png"
    )
    assert out["dominant_color"] == "#008080"
    assert out["orientation"] == "landscape"
    assert out["aspect_ratio"] == 2.0
    assert out["alt_text"] == "Hero banner"


def test_image_orientation_portrait_and_square(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    tall = ImageIngestionPipeline.process(
        _png_b64((10, 10, 10), (100, 300)), str(assets)
    )
    square = ImageIngestionPipeline.process(
        _png_b64((10, 10, 10), (256, 256)), str(assets)
    )
    assert tall["orientation"] == "portrait"
    assert square["orientation"] == "square"


def test_alt_from_filename_variants():
    assert _alt_from_filename("team_photo_2.jpg", 10, 10) == "Team photo 2"
    assert _alt_from_filename("", 640, 480) == "Uploaded image (640x480)"
    assert _alt_from_filename("our-Team.webp", 10, 10) == "Our Team"


def test_document_structure_extraction():
    text = (
        "Jane Doe\n"
        "\n"
        "Senior Engineer with ten years building web platforms.\n"
        "\n"
        "EXPERIENCE\n"
        "Led the reconstruction team.\n"
        "\n"
        "Contact: jane@example.com or see https://jane.dev\n"
    )
    s = DocumentIngestionPipeline._structure(text)
    assert s["title"] == "Jane Doe"
    assert "EXPERIENCE" in s["headings"]
    assert s["summary"].startswith("Jane Doe")
    assert "jane@example.com" in s["emails"]
    assert "https://jane.dev" in s["urls"]
    assert s["word_count"] > 0 and s["line_count"] > 0


def test_document_structure_empty():
    s = DocumentIngestionPipeline._structure("   \n  \n")
    assert s["title"] is None
    assert s["headings"] == [] and s["emails"] == [] and s["urls"] == []
    assert s["word_count"] == 0


def test_document_process_returns_structure(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    raw = "Portfolio\n\nI build delightful interfaces.\n"
    b64 = base64.b64encode(raw.encode()).decode()
    out = DocumentIngestionPipeline.process(
        b64, str(assets), original_filename="bio.txt"
    )
    assert out["structure"]["title"] == "Portfolio"
    assert out["structure"]["summary"].startswith("Portfolio")
