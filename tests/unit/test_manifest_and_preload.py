"""PWA manifest icon localization + <link rel=preload/prefetch> rewriting."""

import glob
import json
import os

import pytest

from wire.agents.extraction.asset_downloader import AssetDownloader


class _Resp:
    def __init__(self, content=b"x", status=200, text=""):
        self.content = content
        self.text = text or content.decode(errors="ignore")
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


MANIFEST = {
    "name": "App",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icons/icon-512.png", "sizes": "512x512"},
        {"src": "data:image/png;base64,AAAA", "sizes": "1x1"},
    ],
    "screenshots": [{"src": "shot.png", "sizes": "540x720"}],
    "shortcuts": [{"name": "New", "icons": [{"src": "sc.png", "sizes": "96x96"}]}],
}


@pytest.mark.asyncio
async def test_manifest_icons_localized_relative_to_manifest_url(tmp_path):
    dl = _dl(
        {
            "https://example.com/pwa/manifest.webmanifest": _Resp(
                content=json.dumps(MANIFEST).encode()
            ),
            "https://example.com/pwa/icon-192.png": _Resp(content=b"\x89PNG192"),
            "https://example.com/icons/icon-512.png": _Resp(content=b"\x89PNG512"),
            "https://example.com/pwa/shot.png": _Resp(content=b"\x89PNGshot"),
            "https://example.com/pwa/sc.png": _Resp(content=b"\x89PNGsc"),
        }
    )
    html = (
        '<html><head><link rel="manifest" href="pwa/manifest.webmanifest">'
        "</head><body></body></html>"
    )
    out, assets = await dl.download_assets("https://example.com/", html, str(tmp_path))

    # Icons resolved against the manifest URL (not the page URL).
    assert "https://example.com/pwa/icon-192.png" in dl.client.calls
    assert "https://example.com/icons/icon-512.png" in dl.client.calls
    assert "https://example.com/pwa/shot.png" in dl.client.calls
    assert "https://example.com/pwa/sc.png" in dl.client.calls

    # The saved manifest points at bare local filenames (it sits in assets/
    # alongside the icons); the data: icon is untouched.
    manifest_files = glob.glob(os.path.join(tmp_path, "*_manifest.webmanifest"))
    assert manifest_files
    saved = json.loads(open(manifest_files[0], encoding="utf-8").read())
    assert saved["icons"][0]["src"].endswith("_icon-192.png")
    assert "/" not in saved["icons"][0]["src"]
    assert saved["icons"][1]["src"].endswith("_icon-512.png")
    assert saved["icons"][2]["src"].startswith("data:")
    assert saved["screenshots"][0]["src"].endswith("_shot.png")
    assert saved["shortcuts"][0]["icons"][0]["src"].endswith("_sc.png")


@pytest.mark.asyncio
async def test_non_json_manifest_saved_untouched(tmp_path):
    dl = _dl(
        {
            "https://example.com/manifest.json": _Resp(content=b"not json at all"),
        }
    )
    html = (
        '<html><head><link rel="manifest" href="manifest.json">'
        "</head><body></body></html>"
    )
    await dl.download_assets("https://example.com/", html, str(tmp_path))
    files = glob.glob(os.path.join(tmp_path, "*_manifest.json"))
    assert files
    assert open(files[0], encoding="utf-8").read() == "not json at all"


@pytest.mark.asyncio
async def test_preload_font_and_prefetch_script_localized(tmp_path):
    dl = _dl(
        {
            "https://example.com/brand.woff2": _Resp(content=b"wOF2"),
            "https://example.com/next.js": _Resp(content=b"//js"),
            "https://example.com/mod.js": _Resp(content=b"//mod"),
        }
    )
    html = (
        "<html><head>"
        '<link rel="preload" href="brand.woff2" as="font" type="font/woff2" '
        'crossorigin integrity="sha384-x">'
        '<link rel="prefetch" href="next.js" as="script">'
        '<link rel="modulepreload" href="mod.js">'
        '<link rel="preconnect" href="https://fonts.gstatic.com">'
        '<link rel="dns-prefetch" href="//cdn.example.net">'
        "</head><body></body></html>"
    )
    out, assets = await dl.download_assets("https://example.com/", html, str(tmp_path))

    assert "https://example.com/brand.woff2" in dl.client.calls
    assert "https://example.com/next.js" in dl.client.calls
    assert "https://example.com/mod.js" in dl.client.calls
    assert 'href="brand.woff2"' not in out
    assert out.count('href="assets/') == 3
    # SRI hash no longer matches the (potentially re-encoded) local file.
    assert "integrity" not in out

    # Origin-level hints are not files; they stay untouched.
    assert 'href="https://fonts.gstatic.com"' in out
    assert 'href="//cdn.example.net"' in out
    assert "https://fonts.gstatic.com" not in dl.client.calls


@pytest.mark.asyncio
async def test_preloaded_stylesheet_processed_as_css(tmp_path):
    css = ".x{background:url(bg.png)}"
    dl = _dl(
        {
            "https://example.com/app.css": _Resp(content=css.encode(), text=css),
            "https://example.com/bg.png": _Resp(content=b"\x89PNG"),
        }
    )
    html = (
        '<html><head><link rel="preload" href="app.css" as="style">'
        "</head><body></body></html>"
    )
    await dl.download_assets("https://example.com/", html, str(tmp_path))
    # Nested url() inside the preloaded sheet was followed and localized.
    assert "https://example.com/bg.png" in dl.client.calls
    css_files = glob.glob(os.path.join(tmp_path, "*_app.css"))
    assert css_files
    assert "url(" in open(css_files[0], encoding="utf-8").read()
    assert "bg.png)" not in open(css_files[0], encoding="utf-8").read().replace(
        "_bg.png", ""
    )
