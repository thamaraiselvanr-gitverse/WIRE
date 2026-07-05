"""@import chains are fetched, recursively localized, and rewritten offline."""

import glob
import os

import pytest

from wire.agents.extraction.asset_downloader import AssetDownloader


class _Resp:
    def __init__(self, text="", content=None, status=200):
        self.text = text
        self.content = content if content is not None else text.encode()
        self.status_code = status


class _FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def get(self, url, follow_redirects=False):
        self.calls.append(url)
        return self.routes.get(url, _Resp(status=404))


@pytest.mark.asyncio
async def test_import_url_form_is_fetched_recursively_and_rewritten(tmp_path):
    dl = AssetDownloader()
    dl._seen_css_imports = set()
    dl.client = _FakeClient(
        {
            "https://ex.com/theme.css": _Resp(text='.x { background: url("bg.png"); }'),
            "https://ex.com/bg.png": _Resp(content=b"\x89PNG"),
        }
    )
    downloaded: list = []
    out = await dl._process_css_urls(
        '@import url("theme.css"); body { color: red; }',
        "https://ex.com/main.css",
        str(tmp_path),
        downloaded,
    )

    assert "https://ex.com/theme.css" in dl.client.calls
    assert "https://ex.com/bg.png" in dl.client.calls  # nested url() followed
    # Rewritten to string-form pointing at the localized copy (bare name because
    # the importing sheet itself lives in assets/).
    assert '@import "' in out and "_theme.css" in out
    assert 'url("theme.css")' not in out
    assert glob.glob(os.path.join(tmp_path, "*_theme.css"))
    assert glob.glob(os.path.join(tmp_path, "*_bg.png"))


@pytest.mark.asyncio
async def test_bare_string_import_is_localized(tmp_path):
    dl = AssetDownloader()
    dl._seen_css_imports = set()
    dl.client = _FakeClient(
        {"https://ex.com/base.css": _Resp(text="h1 { color: teal; }")}
    )
    out = await dl._process_css_urls(
        '@import "base.css";',
        "https://ex.com/app.css",
        str(tmp_path),
        [],
    )
    assert "https://ex.com/base.css" in dl.client.calls
    assert '@import "' in out and "_base.css" in out


@pytest.mark.asyncio
async def test_import_cycle_is_guarded(tmp_path):
    dl = AssetDownloader()
    dl._seen_css_imports = set()
    # a.css imports b.css which imports a.css back.
    dl.client = _FakeClient(
        {
            "https://ex.com/a.css": _Resp(text='@import "b.css";'),
            "https://ex.com/b.css": _Resp(text='@import "a.css";'),
        }
    )
    out = await dl._process_css_urls(
        '@import "a.css";', "https://ex.com/root.css", str(tmp_path), []
    )
    # Terminates; each URL fetched at most once.
    assert dl.client.calls.count("https://ex.com/a.css") == 1
    assert dl.client.calls.count("https://ex.com/b.css") == 1
    assert "_a.css" in out


@pytest.mark.asyncio
async def test_inline_style_import_uses_assets_prefix(tmp_path):
    dl = AssetDownloader()
    dl.client = _FakeClient({"https://ex.com/w.css": _Resp(text="p { margin: 0; }")})
    html = '<html><head><style>@import "w.css";</style></head><body></body></html>'
    out_html, _ = await dl.download_assets(
        "https://ex.com/page.html", html, str(tmp_path)
    )
    # HTML/inline source needs the assets/ prefix to reach the file.
    assert '@import "assets/' in out_html
