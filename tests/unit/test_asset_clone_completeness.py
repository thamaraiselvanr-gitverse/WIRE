"""Clone-completeness gaps: <base href>, meta images, SVG sprites, url() safety."""

import glob
import os

import pytest

from wire.agents.extraction.asset_downloader import AssetDownloader, _is_unfetchable


class _Resp:
    def __init__(self, content=b"x", status=200, text=""):
        self.content = content
        self.text = text
        self.status_code = status


class _FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def get(self, url, follow_redirects=False):
        self.calls.append(url)
        return self.routes.get(url, _Resp(status=404))


def _dl(routes):
    dl = AssetDownloader()
    dl.client = _FakeClient(routes)
    return dl


def test_is_unfetchable():
    assert _is_unfetchable("#frag")
    assert _is_unfetchable("javascript:void(0)")
    assert _is_unfetchable("mailto:a@b.com")
    assert _is_unfetchable("tel:+123")
    assert not _is_unfetchable("https://x/y.png")
    assert not _is_unfetchable("a.css")


@pytest.mark.asyncio
async def test_base_href_retargets_relative_urls(tmp_path):
    dl = _dl({"https://cdn.example.com/app/logo.png": _Resp(content=b"\x89PNG")})
    html = (
        '<html><head><base href="https://cdn.example.com/app/"></head>'
        '<body><img src="logo.png"></body></html>'
    )
    out, _ = await dl.download_assets(
        "https://example.com/page.html", html, str(tmp_path)
    )
    # Resolved against <base>, not the document URL.
    assert "https://cdn.example.com/app/logo.png" in dl.client.calls
    assert 'src="assets/' in out


@pytest.mark.asyncio
async def test_meta_image_is_downloaded_and_rewritten(tmp_path):
    dl = _dl({"https://example.com/og.jpg": _Resp(content=b"\xff\xd8\xff")})
    html = (
        "<html><head>"
        '<meta property="og:image" content="https://example.com/og.jpg">'
        '<meta name="twitter:image" content="https://example.com/og.jpg">'
        "</head><body></body></html>"
    )
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert "https://example.com/og.jpg" in dl.client.calls
    assert 'content="assets/' in out
    assert glob.glob(os.path.join(tmp_path, "*_og.jpg"))


@pytest.mark.asyncio
async def test_svg_use_sprite_localized_keeping_fragment(tmp_path):
    dl = _dl({"https://example.com/sprite.svg": _Resp(content=b"<svg></svg>")})
    html = '<html><body><svg><use href="sprite.svg#home"></use></svg></body></html>'
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert "https://example.com/sprite.svg" in dl.client.calls
    assert "#home" in out
    assert 'href="assets/' in out


@pytest.mark.asyncio
async def test_css_url_fragment_and_scheme_skipped(tmp_path):
    dl = _dl({})  # nothing should be fetched
    css = ".a{filter:url(#blur)} .b{cursor:url(javascript:0),auto} .c{color:red}"
    out = await dl._process_css_urls(
        css, "https://example.com/x.css", str(tmp_path), []
    )
    assert dl.client.calls == []  # no bogus downloads
    assert "url(#blur)" in out


@pytest.mark.asyncio
async def test_mailto_and_fragment_not_fetched_as_assets(tmp_path):
    dl = _dl({})
    # <a> hrefs aren't localized anyway, but a data-src fragment must be skipped.
    html = '<html><body><img data-src="#local"></body></html>'
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert dl.client.calls == []
    assert 'data-src="#local"' in out
