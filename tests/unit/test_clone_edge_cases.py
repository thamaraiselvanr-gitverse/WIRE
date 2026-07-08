"""Edge-case clone fixes: dedup, charset, DOCTYPE, protocol-relative URLs."""

import glob
import os

import pytest

from wire.agents.extraction.asset_downloader import AssetDownloader


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


# --- Dedup: same URL fetched once -------------------------------------------


@pytest.mark.asyncio
async def test_repeated_url_fetched_once(tmp_path):
    dl = _dl({"https://example.com/logo.png": _Resp(content=b"\x89PNG")})
    html = (
        '<html><body><img src="logo.png"><img src="logo.png">'
        '<img src="logo.png"></body></html>'
    )
    out, assets = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert dl.client.calls.count("https://example.com/logo.png") == 1
    assert len(assets) == 1
    # All three tags rewritten to the same local file.
    assert out.count('src="assets/') == 3


@pytest.mark.asyncio
async def test_identical_content_different_urls_saved_once(tmp_path):
    png = b"\x89PNG-identical-bytes"
    dl = _dl(
        {
            "https://example.com/a.png": _Resp(content=png),
            "https://cdn.example.com/b.png": _Resp(content=png),
        }
    )
    html = (
        '<html><body><img src="a.png">'
        '<img src="https://cdn.example.com/b.png"></body></html>'
    )
    out, assets = await dl.download_assets("https://example.com/", html, str(tmp_path))
    # Both URLs fetched (bytes unknown until fetched), but only one file saved.
    assert len(assets) == 1
    files = glob.glob(os.path.join(tmp_path, "*.png"))
    assert len(files) == 1
    # Both tags point at the one local copy.
    local = "assets/" + os.path.basename(files[0])
    assert out.count(f'src="{local}"') == 2


@pytest.mark.asyncio
async def test_css_url_reuses_asset_downloaded_from_html(tmp_path):
    dl = _dl(
        {
            "https://example.com/bg.png": _Resp(content=b"\x89PNG"),
            "https://example.com/style.css": _Resp(
                content=b"body{background:url(bg.png)}",
                text="body{background:url(bg.png)}",
            ),
        }
    )
    html = (
        '<html><head><link rel="stylesheet" href="style.css"></head>'
        '<body><img src="bg.png"></body></html>'
    )
    await dl.download_assets("https://example.com/", html, str(tmp_path))
    # bg.png referenced from both HTML and CSS: fetched exactly once.
    assert dl.client.calls.count("https://example.com/bg.png") == 1


# --- Charset normalization ---------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_charset_rewritten_to_utf8(tmp_path):
    dl = _dl({})
    html = (
        '<html><head><meta charset="iso-8859-1"><title>x</title></head>'
        "<body>café</body></html>"
    )
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert 'charset="utf-8"' in out
    assert "iso-8859-1" not in out


@pytest.mark.asyncio
async def test_http_equiv_content_type_charset_rewritten(tmp_path):
    dl = _dl({})
    html = (
        "<html><head>"
        '<meta http-equiv="Content-Type" content="text/html; charset=Shift_JIS">'
        "</head><body>x</body></html>"
    )
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert "charset=utf-8" in out
    assert "Shift_JIS" not in out


@pytest.mark.asyncio
async def test_missing_charset_declaration_inserted(tmp_path):
    dl = _dl({})
    html = "<html><head><title>x</title></head><body>naïve</body></html>"
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert 'charset="utf-8"' in out


@pytest.mark.asyncio
async def test_headless_fragment_gets_no_charset_injection(tmp_path):
    dl = _dl({})
    html = "<div>partial</div>"
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert "charset" not in out


# --- DOCTYPE + script attribute passthrough ----------------------------------


@pytest.mark.asyncio
async def test_doctype_preserved_through_localization(tmp_path):
    dl = _dl({})
    html = "<!DOCTYPE html><html><head></head><body><p>hi</p></body></html>"
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert out.lstrip().lower().startswith("<!doctype html>")


@pytest.mark.asyncio
async def test_no_doctype_is_not_invented(tmp_path):
    # A quirks-mode page must stay quirks-mode: don't inject a doctype.
    dl = _dl({})
    html = "<html><head></head><body><p>hi</p></body></html>"
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert "doctype" not in out.lower()


@pytest.mark.asyncio
async def test_script_defer_async_module_attrs_survive(tmp_path):
    dl = _dl({"https://example.com/app.js": _Resp(content=b"//js")})
    html = (
        "<html><head>"
        '<script src="app.js" defer></script>'
        '<script src="app.js" async type="module"></script>'
        "</head><body></body></html>"
    )
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert "defer" in out
    assert "async" in out
    assert 'type="module"' in out


# --- Protocol-relative URLs ---------------------------------------------------


@pytest.mark.asyncio
async def test_protocol_relative_url_resolved_with_page_scheme(tmp_path):
    dl = _dl({"https://cdn.example.net/lib.js": _Resp(content=b"//js")})
    html = '<html><body><script src="//cdn.example.net/lib.js"></script></body></html>'
    out, _ = await dl.download_assets("https://example.com/", html, str(tmp_path))
    assert "https://cdn.example.net/lib.js" in dl.client.calls
    assert 'src="assets/' in out
