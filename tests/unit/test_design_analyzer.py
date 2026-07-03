from wire.agents.extraction.design_analyzer import DesignAnalyzer

CSS = """
  body { color: #333333; background-color: #ffffff; font-family: Arial, sans-serif; }
  h1 { color: #333333; font-family: Georgia, serif; font-size: 2rem; }
  p { color: #333333; font-size: 16px; margin: 8px; }
  .accent { color: rgb(255, 0, 0); }
  .card { padding: 24px; margin: 16px; background: #f0f0f0 url(x.png); }
  @media (max-width: 600px) { p { font-size: 14px; } }
"""


def _analyze(css: str):
    return DesignAnalyzer().extract_design_architecture("<html></html>", css)


def test_colors_are_normalized_and_frequency_ranked():
    tokens = _analyze(CSS)
    colors = tokens["colors"]
    # #333333 is the most frequent foreground color -> primary.
    assert colors["primary"] == "#333333"
    # rgb(255,0,0) normalized to hex and present as a secondary/accent color.
    assert "#ff0000" in colors.values()
    # Background captured from background-color.
    assert colors["background"] == "#ffffff"


def test_typography_families_and_size_scale():
    tokens = _analyze(CSS)
    typo = tokens["typography"]
    assert typo["base"] == "Arial, sans-serif"  # most frequent family
    assert typo["heading"] == "Georgia, serif"
    # Sizes normalized to px and ordered ascending (14, 16, 32).
    sizes = [v for k, v in typo.items() if k.startswith("size-")]
    assert "14px" in sizes and "16px" in sizes and "32px" in sizes
    assert sizes == sorted(sizes, key=lambda s: float(s.rstrip("px")))


def test_spacing_scale_sorted_ascending_with_semantic_names():
    tokens = _analyze(CSS)
    spacing = tokens["spacing"]
    # Collected spacing: 8, 16, 24 -> xs/sm/md ascending.
    assert spacing["xs"] == "8px"
    assert spacing["sm"] == "16px"
    assert spacing["md"] == "24px"


def test_empty_css_returns_sensible_defaults():
    tokens = _analyze("")
    assert tokens["colors"]["primary"]
    assert tokens["typography"]["base"]
    assert tokens["spacing"]


def test_rem_spacing_converted_to_px():
    tokens = _analyze("div { padding: 1rem; margin: 2rem; }")
    values = set(tokens["spacing"].values())
    assert "16px" in values  # 1rem
    assert "32px" in values  # 2rem
