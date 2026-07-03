from wire.compilers.html_compiler import HTMLCompiler
from wire.schema.canonical import (
    CanonicalDesignSchema,
    ComponentNode,
    HTMLToCidsParser,
)
from wire.schema.style_mapper import CascadeResolver

DOC_HTML = """
<html><head><style>
  @font-face { font-family: 'Brand'; src: url('brand.woff2'); }
  .hero { color: #000; }
  .hero:hover { color: #f00; }
  @media (max-width: 600px) { .hero { display: none; } }
</style></head>
<body><div class="hero">Hi</div></body></html>
"""


def _build_cids():
    resolver = CascadeResolver()
    soup, style_map = resolver.resolve(DOC_HTML, "")
    root = HTMLToCidsParser.parse(
        soup,
        style_map,
        responsive_map=resolver.responsive_map,
        pseudo_map=resolver.pseudo_map,
    )
    return CanonicalDesignSchema(
        url="http://example.com", root=root, global_styles=resolver.global_styles
    )


def test_compile_document_is_full_html5_document():
    doc = HTMLCompiler().compile_document(_build_cids())
    assert doc.lstrip().startswith("<!doctype html>")
    assert "<html" in doc and "</html>" in doc
    assert "<head>" in doc and "</head>" in doc
    assert "<body>" in doc and "</body>" in doc
    assert 'charset="utf-8"' in doc
    assert "viewport" in doc


def test_compile_document_puts_styles_in_head_not_body():
    doc = HTMLCompiler().compile_document(_build_cids())
    head = doc[doc.index("<head>") : doc.index("</head>")]
    body = doc[doc.index("<body>") : doc.index("</body>")]
    # The generated stylesheet (webfont + media + hover) belongs in <head>.
    assert "<style>" in head
    assert "@font-face" in head
    assert "@media" in head
    assert ":hover" in head
    assert "<style>" not in body
    # The actual content lives in <body>.
    assert "hero" in body


def test_compile_document_does_not_nest_body():
    # The CIDS root is the <body> element; the document build must unwrap it
    # rather than nesting a second <body> inside its own.
    doc = HTMLCompiler().compile_document(_build_cids())
    assert doc.count("<body") == 1
    assert doc.count("</body>") == 1


def test_compile_document_uses_title():
    doc = HTMLCompiler().compile_document(_build_cids(), title="My Page")
    assert "<title>My Page</title>" in doc


def test_compile_document_defaults_title_to_url():
    doc = HTMLCompiler().compile_document(_build_cids())
    assert "<title>http://example.com</title>" in doc


def test_compile_fragment_behavior_unchanged():
    # The original fragment API must still return a body fragment (style block
    # prefixed), not a full document.
    root = ComponentNode(
        tag="div", children=[ComponentNode(tag="#text", text_content="x")]
    )
    cids = CanonicalDesignSchema(url="http://x", root=root)
    out = HTMLCompiler().compile(cids)
    assert not out.lstrip().startswith("<!doctype")
    assert out.startswith("<div>")
