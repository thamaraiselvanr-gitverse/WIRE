"""Opt-in tracker stripping: signature-based, conservative, fully reported."""

from wire.agents.extraction.tracker_stripper import (
    TrackerStripper,
    _is_tracker_url,
)
from wire.orchestrator.execution_router import ExecutionRouter


def test_tracker_url_matching():
    assert _is_tracker_url("https://www.google-analytics.com/analytics.js")
    assert _is_tracker_url("https://connect.facebook.net/en_US/fbevents.js")
    assert _is_tracker_url("//static.hotjar.com/c/hotjar-1.js")  # protocol-relative
    assert _is_tracker_url("https://www.facebook.com/tr?id=1&ev=PageView")
    # Similar-looking but non-tracker hosts must not match by substring.
    assert not _is_tracker_url("https://notgoogle-analytics.com/x.js")
    assert not _is_tracker_url("https://example.com/app.js")
    assert not _is_tracker_url("https://cdn.jsdelivr.net/lib.js")


def test_external_and_inline_trackers_removed():
    html = """<html><head>
    <script src="https://www.googletagmanager.com/gtag/js?id=G-XXX" async></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){dataLayer.push(arguments);}
      gtag('js', new Date()); gtag('config', 'G-XXX');
    </script>
    <script src="/js/app.js"></script>
    <script>document.querySelector('#menu').addEventListener('click', run);</script>
    </head><body><p>content</p></body></html>"""
    out, report = TrackerStripper().strip(html)
    assert "googletagmanager" not in out
    assert "gtag" not in out
    # First-party script and ordinary inline JS are untouched.
    assert 'src="/js/app.js"' in out
    assert "addEventListener" in out
    assert report["removed"]["external_scripts"] == 1
    assert report["removed"]["inline_scripts"] == 1
    assert report["total_removed"] == 2


def test_pixels_iframes_and_noscript_shells_removed():
    html = """<html><body>
    <noscript><img height="1" width="1"
      src="https://www.facebook.com/tr?id=123&ev=PageView&noscript=1"></noscript>
    <iframe src="https://www.googletagmanager.com/ns.html?id=GTM-X"
      height="0" width="0"></iframe>
    <img src="/logo.png">
    <noscript><p>Enable JS for the menu.</p></noscript>
    </body></html>"""
    out, report = TrackerStripper().strip(html)
    assert "facebook.com/tr" not in out
    assert "googletagmanager" not in out
    assert 'src="/logo.png"' in out
    # The pixel's now-empty <noscript> shell is dropped; the real one stays.
    assert out.count("<noscript>") == 1
    assert "Enable JS" in out
    assert report["removed"]["pixels"] == 1
    assert report["removed"]["iframes"] == 1


def test_hints_verification_meta_and_ping_removed():
    html = """<html><head>
    <link rel="preconnect" href="https://www.google-analytics.com">
    <link rel="dns-prefetch" href="//mc.yandex.ru">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <meta name="google-site-verification" content="abc123">
    <meta name="description" content="kept">
    </head><body>
    <a href="/pricing" ping="https://tracker.example/ping">Pricing</a>
    </body></html>"""
    out, report = TrackerStripper().strip(html)
    assert "google-analytics" not in out
    assert "mc.yandex.ru" not in out
    assert "fonts.gstatic.com" in out  # functional preconnect kept
    assert "google-site-verification" not in out
    assert 'name="description"' in out
    assert "ping=" not in out
    assert 'href="/pricing"' in out  # link itself survives, beacon attr gone
    assert report["removed"]["resource_hints"] == 2
    assert report["removed"]["verification_meta"] == 1
    assert report["removed"]["ping_attributes"] == 1


def test_matched_urls_are_reported_for_audit():
    html = (
        '<html><head><script src="https://cdn.segment.com/analytics.js/v1/x">'
        "</script></head><body></body></html>"
    )
    _, report = TrackerStripper().strip(html)
    assert report["matched_urls"] == ["https://cdn.segment.com/analytics.js/v1/x"]


def test_clean_page_is_untouched():
    html = (
        "<html><head><script>const state = {loaded: true};</script></head>"
        '<body><img src="hero.png"><p>hi</p></body></html>'
    )
    out, report = TrackerStripper().strip(html)
    assert report["total_removed"] == 0
    assert "hero.png" in out and "state" in out


def test_router_flag_is_opt_in():
    # Default pipeline promise is fidelity: stripping must be off by default.
    assert ExecutionRouter().enable_tracker_stripping is False
