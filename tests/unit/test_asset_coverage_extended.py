"""Extended asset-localization coverage: srcset, <picture>/<source>, lazy
data-src, <video>/<audio>/<track>, poster images, and favicons/icons.

These are common on modern sites and were previously ignored by the downloader,
so the pixel-faithful clone silently lost responsive images, media, and icons.
Uses httpx.MockTransport so no network is required.
"""

import os

import httpx
import pytest

from wire.agents.extraction.asset_downloader import AssetDownloader

_PNG = b"\x89PNG\r\n\x1a\n"


async def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".avif", ".ico", ".gif", ".svg")
    ):
        return httpx.Response(200, content=_PNG, headers={"content-type": "image/png"})
    if url.endswith((".mp4", ".webm", ".mp3", ".ogg", ".vtt")):
        return httpx.Response(
            200, content=b"\x00\x00", headers={"content-type": "video/mp4"}
        )
    if url.endswith(".webmanifest"):
        return httpx.Response(200, text="{}", headers={"content-type": "text/plain"})
    return httpx.Response(404)


HTML = """<html><head>
  <link rel="icon" href="favicon.ico">
  <link rel="apple-touch-icon" href="touch.png">
  <link rel="mask-icon" href="mask.svg" color="#000">
  <link rel="manifest" href="site.webmanifest">
</head><body>
  <img src="hero.png" srcset="hero-400.png 400w, hero-800.png 800w"
       data-src="lazy.jpg" data-srcset="lazy-2x.jpg 2x">
  <picture>
    <source type="image/webp" srcset="art.webp 1x, art-2x.webp 2x">
    <source type="image/jpeg" src="art.jpg">
    <img src="fallback.png">
  </picture>
  <video src="movie.mp4" poster="poster.jpg">
    <source src="movie.webm" type="video/webm">
    <track src="subs.vtt" kind="subtitles">
  </video>
  <audio><source src="tune.mp3" type="audio/mpeg"></audio>
</body></html>"""


@pytest.mark.asyncio
async def test_extended_asset_localization(tmp_path):
    assets_dir = str(tmp_path / "assets")
    os.makedirs(assets_dir)

    dl = AssetDownloader()
    dl.client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        rewritten, assets = await dl.download_assets(
            "http://site.com/", HTML, assets_dir
        )
    finally:
        await dl.client.aclose()

    # No original (un-localized) attribute value should survive: every asset
    # reference is rewritten to an ``assets/<hash>_name`` path.
    for stale in (
        'href="favicon.ico"',
        'href="touch.png"',
        'href="site.webmanifest"',
        'href="mask.svg"',
        'src="movie.mp4"',
        'poster="poster.jpg"',
        'src="movie.webm"',
        'src="subs.vtt"',
        'src="tune.mp3"',
        'src="art.jpg"',
        'src="fallback.png"',
        'data-src="lazy.jpg"',
    ):
        assert stale not in rewritten, f"un-localized reference remained: {stale}"

    # srcset URLs rewritten while width/density descriptors are preserved.
    assert "400w" in rewritten and "800w" in rewritten and "2x" in rewritten
    assert 'srcset="hero-400.png' not in rewritten  # URL part must be localized
    assert "assets/" in rewritten and "assets/" in rewritten.split("srcset=")[1]

    # Every discovered asset actually hit disk (icons + images + media + tracks).
    assert len(os.listdir(assets_dir)) >= 12
