from wire.compilers.html_compiler import HTMLCompiler
from wire.schema.canonical import (
    CanonicalDesignSchema,
    ComponentNode,
    HTMLToCidsParser,
)
from wire.schema.style_mapper import CascadeResolver

RESPONSIVE_HTML = """
<html><head><style>
  .box { width: 100%; color: #000; }
  @media (max-width: 768px) {
    .box { width: 50%; display: none; }
  }
</style></head>
<body><div class="box">hi</div></body></html>
"""


def test_cascade_resolver_captures_media_rules():
    resolver = CascadeResolver()
    soup, style_map = resolver.resolve(RESPONSIVE_HTML, "")

    box = soup.select_one(".box")
    assert box is not None
    responsive = resolver.responsive_map.get(id(box))
    assert responsive is not None, "media rule was not captured"

    media_key = next(iter(responsive))
    assert "max-width: 768px" in media_key
    assert responsive[media_key]["width"] == "50%"
    assert responsive[media_key]["display"] == "none"


def test_cids_node_carries_responsive_styles():
    resolver = CascadeResolver()
    soup, style_map = resolver.resolve(RESPONSIVE_HTML, "")
    root = HTMLToCidsParser.parse(
        soup, style_map, responsive_map=resolver.responsive_map
    )

    def find_box(node: ComponentNode):
        if "box" in node.attributes.get("class", ""):
            return node
        for c in node.children:
            found = find_box(c)
            if found:
                return found
        return None

    box_node = find_box(root)
    assert box_node is not None
    assert box_node.responsive_styles, "responsive styles missing on CIDS node"
    media_key = next(iter(box_node.responsive_styles))
    assert box_node.responsive_styles[media_key]["width"] == "50%"


def test_html_compiler_emits_media_style_block():
    resolver = CascadeResolver()
    soup, style_map = resolver.resolve(RESPONSIVE_HTML, "")
    root = HTMLToCidsParser.parse(
        soup, style_map, responsive_map=resolver.responsive_map
    )
    cids = CanonicalDesignSchema(url="http://x", root=root)

    html = HTMLCompiler().compile(cids)
    assert "<style>" in html
    assert "@media" in html
    assert "max-width: 768px" in html
    # The node must gain the generated class that the media rule targets.
    assert "wire-r1" in html


def test_html_compiler_no_style_block_without_responsive():
    root = ComponentNode(
        tag="div", children=[ComponentNode(tag="#text", text_content="x")]
    )
    cids = CanonicalDesignSchema(url="http://x", root=root)
    html = HTMLCompiler().compile(cids)
    assert "<style>" not in html
    assert html.startswith("<div>")
