"""Direct coverage for DesignAnalyzer colour/length normalization and the
top-level design-architecture extraction."""

from wire.agents.extraction.design_analyzer import DesignAnalyzer

nc = DesignAnalyzer._normalize_color
px = DesignAnalyzer._to_px


def test_normalize_color_variants():
    assert nc("rgb(255, 0, 0)") == "#ff0000"
    assert nc("rgba(0, 128, 255, 0.5)") == "#0080ff"
    assert nc("rgb(oops)") is None
    assert nc("#abc") == "#aabbcc"  # shorthand expands
    assert nc("#1a2b3c") == "#1a2b3c"
    assert nc("#1a2b3c80") == "#1a2b3c"  # 8-digit trimmed to 6
    assert nc("#xyz") is None
    assert nc("red") == "red"  # named colour kept
    assert nc("transparent") is None  # non-colour keyword skipped
    assert nc("123abc") is None  # not a colour token
    assert nc("") is None


def test_to_px_units():
    assert px("16px") == 16.0
    assert px("1rem") == 16.0
    assert px("2em") == 32.0
    assert px("12") == 12.0  # unitless treated as px
    assert px("auto") is None


def test_extract_design_architecture_from_css():
    css = """
      body { color: rgb(20, 20, 20); background: #ffffff; font-family: Arial; font-size: 16px; }
      h1 { color: #2b6cb0; font-size: 40px; }
      .box { padding: 24px; margin: 8px; }
    """
    html = "<html><body><style>.extra{color:#333}</style><h1>Hi</h1></body></html>"
    arch = DesignAnalyzer().extract_design_architecture(html, css)
    assert isinstance(arch, dict)
    assert "colors" in arch and "typography" in arch
