"""Adapter parity: React/Vue/HTML all emit @media, pseudo, and @font-face/
@keyframes styling that inline styles cannot express."""

from wire.compilers.html_compiler import HTMLCompiler
from wire.compilers.react_adapter import ReactAdapter
from wire.compilers.vue_adapter import VueAdapter
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode
from wire.schema.style_mapper import CascadeResolver

FONT_ANIM_CSS = """
@font-face { font-family: 'Brand'; src: url('brand.woff2'); }
@keyframes fade { from { opacity: 0; } to { opacity: 1; } }
.hero { color: #000; }
.hero:hover { color: #f00; }
@media (max-width: 600px) { .hero { display: none; } }
"""

HTML = (
    "<html><head><style>" + FONT_ANIM_CSS + "</style></head><body>"
    '<div class="hero">Hi</div></body></html>'
)


def _build_cids():
    from wire.schema.canonical import HTMLToCidsParser

    resolver = CascadeResolver()
    soup, style_map = resolver.resolve(HTML, "")
    root = HTMLToCidsParser.parse(
        soup,
        style_map,
        responsive_map=resolver.responsive_map,
        pseudo_map=resolver.pseudo_map,
    )
    return CanonicalDesignSchema(
        url="http://x", root=root, global_styles=resolver.global_styles
    )


def test_resolver_captures_font_face_and_keyframes():
    resolver = CascadeResolver()
    resolver.resolve(HTML, "")
    joined = "\n".join(resolver.global_styles).lower()
    assert "@font-face" in joined
    assert "@keyframes" in joined


def test_html_compiler_includes_global_styles():
    cids = _build_cids()
    out = HTMLCompiler().compile(cids)
    assert "@font-face" in out
    assert "@keyframes" in out
    assert "@media" in out
    assert ":hover" in out


def test_react_adapter_emits_style_and_class():
    cids = _build_cids()
    out = ReactAdapter().compile(cids)
    # Fragment + style element carrying the non-inline CSS.
    assert "<style dangerouslySetInnerHTML" in out
    assert "@font-face" in out
    assert "@keyframes" in out
    assert ":hover" in out
    # The hero node keeps its class and gains the generated one.
    assert "hero wire-r1" in out


def test_vue_adapter_emits_style_and_class():
    cids = _build_cids()
    out = VueAdapter().compile(cids)
    assert "@font-face" in out
    assert "@keyframes" in out
    assert ":hover" in out
    assert "hero wire-r1" in out


def test_adapters_unchanged_without_generated_styles():
    # A plain tree (no responsive/pseudo/global styles) must not gain a <style>
    # block or generated classes — preserves existing adapter behavior.
    root = ComponentNode(
        tag="div",
        attributes={"id": "root"},
        children=[ComponentNode(tag="#text", text_content="hi")],
    )
    cids = CanonicalDesignSchema(url="http://x", root=root)

    react_out = ReactAdapter().compile(cids)
    assert "<style" not in react_out
    assert "wire-r" not in react_out

    vue_out = VueAdapter().compile(cids)
    assert "wire-r" not in vue_out
