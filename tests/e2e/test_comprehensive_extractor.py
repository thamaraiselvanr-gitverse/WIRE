"""Browser-backed test for the comprehensive design-knowledge extractor."""

import pytest

from wire.agents.extraction.comprehensive_extractor import ComprehensiveExtractor

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Acme Studio</title>
<meta name="description" content="We build things.">
<meta property="og:title" content="Acme">
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="canonical" href="https://acme.test/">
<script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>
<style>
  :root { --brand: #2b6cb0; --space-md: 16px; }
  @font-face { font-family: 'Brand'; src: url('brand.woff2'); font-display: swap; }
  @keyframes fade { from {opacity:0} to {opacity:1} }
  body { font-family: Arial, sans-serif; color:#222; }
  h1 { font-size: 40px; color: #2b6cb0; }
  .btn { background:#e0674f; }
  @media (max-width: 600px){ h1 { font-size: 28px; } }
  @media (min-width: 1024px){ .grid { display:grid; } }
</style></head>
<body>
  <header><nav><a href="#x" class="fa fa-home">Home</a></nav></header>
  <main>
    <h1>Acme Studio</h1>
    <button class="btn">Go</button>
    <form><input type="text" aria-label="name"><textarea></textarea></form>
    <details><summary>Q</summary>A</details>
    <table><tr><td>x</td></tr></table>
    <img src="x.png" alt="x"><img src="y.png">
    <svg viewBox="0 0 10 10"></svg>
  </main>
  <footer></footer>
</body></html>
"""


@pytest.mark.slow
@pytest.mark.asyncio
async def test_comprehensive_extraction_covers_checklist(tmp_path):
    from wire.agents.observation.browser_session import BrowserSession

    site = tmp_path / "site.html"
    site.write_text(PAGE, encoding="utf-8")

    session = BrowserSession()
    await session.start()
    try:
        page = await session.context.new_page()
        await page.goto("file://" + str(site), wait_until="networkidle")
        report = await ComprehensiveExtractor().extract(page)
        await page.close()
    finally:
        await session.stop()

    # 1. Meta & SEO
    assert report["title"] == "Acme Studio"
    assert report["lang"] == "en"
    assert report["meta"].get("description") == "We build things."
    assert report["meta"].get("og:title") == "Acme"
    assert any("favicon" in link["href"] for link in report["links"])
    assert any("canonical" in link["rel"] for link in report["links"])
    assert report["json_ld"] and "Organization" in report["json_ld"][0]

    # 2/5. Design tokens + palette
    assert report["css_variables"].get("--brand") == "#2b6cb0"
    assert report["css_variables"].get("--space-md") == "16px"
    assert any(
        "2b6cb0" in c["color"] or "43, 108, 176" in c["color"]
        for c in report["color_palette"]
    )

    # 3. Typography (computed)
    assert report["typography"]["h1"]["font_size"] == "40px"

    # Webfonts + animations + breakpoints
    assert any(f["family"].strip("'\" ") == "Brand" for f in report["font_faces"])
    assert "fade" in report["keyframes"]
    assert "600px" in report["breakpoints"]
    assert "1024px" in report["breakpoints"]

    # 4. Icon library
    assert report["icon_library"] == "font-awesome"

    # 22. Accessibility inventory
    a = report["accessibility"]
    assert a["landmarks"]["nav"] == 1 and a["landmarks"]["main"] == 1
    assert a["images_total"] == 2 and a["images_with_alt"] == 1
    assert a["lang_set"] is True

    # Component inventory
    c = report["components"]
    assert c["buttons"] >= 1 and c["forms"] == 1 and c["inputs"] == 2
    assert c["accordions"] >= 1 and c["tables"] == 1 and c["svgs"] == 1
