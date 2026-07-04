"""Coverage for asset_downloader branches: nested CSS url() download+rewrite,
data-URI passthrough, inline <style> processing, and failed-download fallback."""

import os

import httpx
import pytest

from wire.agents.extraction.asset_downloader import AssetDownloader

_PNG = b"\x89PNG\r\n\x1a\n"


async def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith("main.css"):
        # CSS that references a font and a background image via url().
        return httpx.Response(
            200,
            text="@font-face{font-family:X;src:url(brand.woff2)} .h{background:url(bg.png)}",
            headers={"content-type": "text/css"},
        )
    if url.endswith((".woff2", ".png", ".jpg")):
        return httpx.Response(200, content=_PNG)
    if url.endswith("missing.js"):
        return httpx.Response(404)
    return httpx.Response(404)


HTML = """<html><head>
  <link rel="stylesheet" href="main.css">
  <script src="missing.js"></script>
</head><body>
  <img src="data:image/png;base64,AAAA">
  <img src="photo.jpg">
  <style>.hero{background:url(hero.png)}</style>
</body></html>"""


@pytest.mark.asyncio
async def test_asset_downloader_branches(tmp_path):
    assets = str(tmp_path / "assets")
    os.makedirs(assets)
    dl = AssetDownloader()
    dl.client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        rewritten, downloaded = await dl.download_assets(
            "http://site.test/", HTML, assets
        )
    finally:
        await dl.client.aclose()

    # The data: URI image is passed through untouched (not downloaded).
    assert "data:image/png;base64,AAAA" in rewritten
    # The stylesheet and its nested font/bg were localized.
    assert any("main.css" in os.path.basename(p) for p in downloaded)
    assert any("brand.woff2" in os.path.basename(p) for p in downloaded)
    # The failed script download leaves the original reference in place.
    assert "missing.js" in rewritten
    # Inline <style> url() was rewritten into assets/.
    assert "assets/" in rewritten
