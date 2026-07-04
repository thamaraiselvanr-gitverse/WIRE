"""Branch coverage for HtmlSanitizer: URI safety, style-string filtering
(expression/behavior/url payloads, data-URI allowlist), and full-HTML sanitize.
"""

from wire.compilers.sanitizer import HtmlSanitizer

san = HtmlSanitizer._sanitize_style_string
uri = HtmlSanitizer._is_safe_uri


def test_is_safe_uri():
    assert uri("") is True
    assert (
        uri("  ") is True
    )  # whitespace-only -> empty after strip is False-y? relative
    assert uri("/local/path") is True
    assert uri("https://ok.test/x") is True
    assert uri("javascript:alert(1)") is False
    assert uri("ftp://host/file") is False  # not in safe protocols


def test_style_string_trivial_and_dangerous_keywords():
    assert san("") == ""
    assert san("   )") == ""
    assert san("()") == ""
    assert san("width: expression(alert(1))") == ""
    assert san("background: url(javascript:alert(1))") == ""
    assert san("behavior: url(x.htc)") == ""


def test_style_string_keeps_safe_and_drops_unsafe_alongside():
    out = san("color: red; width: expression(bad); padding: 4px")
    assert "color: red" in out and "padding: 4px" in out
    assert "expression" not in out


def test_style_string_url_variants():
    # Safe image data URI kept (comma form; the sanitizer splits on ';').
    ok = san("background: url(data:image/png,AAAA)")
    assert "url(data:image/png" in ok
    # Disallowed data type (html) dropped.
    assert san("background: url(data:text/html,xx)") == ""
    # Bracket / error / about: injections dropped.
    assert san("background: url(about:blank)") == ""
    assert san("background: url([bad url])") == ""
    # Relative image url kept.
    assert "url(pic.png)" in san("background: url(pic.png)")
    # Unsafe protocol dropped.
    assert san("background: url(ftp://h/x.png)") == ""


def test_sanitize_html_strips_scripts_and_events_keeps_safe():
    out = HtmlSanitizer.sanitize_html(
        "<div><script>evil()</script>"
        '<a href="javascript:evil()">bad</a>'
        '<a href="https://ok.test" id="keep">ok</a>'
        '<p style="color: red; behavior: url(x)">hi</p></div>'
    )
    assert "<script>" not in out
    assert "javascript:" not in out
    assert "keep" in out
    assert "color: red" in out
    assert "behavior" not in out


def test_sanitize_html_empty():
    assert HtmlSanitizer.sanitize_html("") == ""
