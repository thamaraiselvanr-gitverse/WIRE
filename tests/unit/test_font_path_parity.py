"""External-CSS @font-face path parity in the editable output.

Webfonts declared in an *external* stylesheet are localized by the downloader to
a bare ``<hash>_name.woff2`` (relative to ``assets/``). Because @font-face is
hoisted verbatim into the editable document's <style> — and that document lives
at the run root — a bare reference must be relocated to ``assets/<name>`` or the
font 404s. Inline-<style> and absolute references must be left alone.
"""

from wire.compilers.html_compiler import HTMLCompiler
from wire.compilers.style_emission import _localize_global_url_refs, safe_global_rules
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode


def test_bare_font_url_is_relocated_under_assets():
    rule = (
        "@font-face { font-family: Brand; src: url(123_brand.woff2) format('woff2') }"
    )
    out = _localize_global_url_refs(rule)
    assert "url(assets/123_brand.woff2)" in out


def test_quotes_preserved_when_relocating():
    assert (
        _localize_global_url_refs("@font-face { src: url('9_x.ttf') }")
        == "@font-face { src: url('assets/9_x.ttf') }"
    )
    assert (
        _localize_global_url_refs('@font-face { src: url("9_x.ttf") }')
        == '@font-face { src: url("assets/9_x.ttf") }'
    )


def test_already_localized_and_absolute_refs_untouched():
    for value in (
        "url(assets/9_x.woff2)",  # inline-<style> source already prefixed
        "url(https://cdn.test/x.woff2)",  # absolute
        "url(//cdn.test/x.woff2)",  # protocol-relative
        "url(/fonts/x.woff2)",  # root-absolute path
        "url(data:font/woff2;base64,AAAA)",  # data URI
        "url(#grad)",  # SVG fragment ref
    ):
        rule = f"@font-face {{ src: {value} }}"
        assert _localize_global_url_refs(rule) == rule


def test_multiple_srcs_in_one_rule():
    rule = "@font-face { src: url(a_1.woff2), url('b_2.ttf'), url(https://x/c.eot) }"
    out = _localize_global_url_refs(rule)
    assert "url(assets/a_1.woff2)" in out
    assert "url('assets/b_2.ttf')" in out
    assert "url(https://x/c.eot)" in out  # absolute untouched


def test_font_face_reaches_editable_document_with_assets_prefix():
    cids = CanonicalDesignSchema(
        url="http://x",
        root=ComponentNode(tag="body", children=[ComponentNode(tag="p")]),
        global_styles=["@font-face { font-family: B; src: url(42_b.woff2) }"],
    )
    doc = HTMLCompiler().compile_document(cids)
    assert "url(assets/42_b.woff2)" in doc
    # The broken bare form must not survive in the emitted stylesheet.
    assert "src: url(42_b.woff2)" not in doc
    assert "@font-face" in doc


def test_safe_global_rules_still_filters_injection():
    assert safe_global_rules(["@font-face { src: url(javascript:alert(1)) }"]) == []
