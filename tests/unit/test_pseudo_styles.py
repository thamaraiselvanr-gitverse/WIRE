from wire.compilers.html_compiler import HTMLCompiler
from wire.schema.canonical import (
    CanonicalDesignSchema,
    ComponentNode,
    HTMLToCidsParser,
)
from wire.schema.style_mapper import CascadeResolver

HOVER_HTML = """
<html><head><style>
  .btn { color: #000; background-color: #eee; }
  .btn:hover { color: #fff; background-color: #333; }
  .btn:focus { border: 2px solid #00f; }
</style></head>
<body><a class="btn" href="#">Click</a></body></html>
"""


def test_cascade_resolver_captures_pseudo_rules():
    resolver = CascadeResolver()
    soup, _ = resolver.resolve(HOVER_HTML, "")
    btn = soup.select_one(".btn")
    pseudo = resolver.pseudo_map.get(id(btn))
    assert pseudo is not None, "pseudo rules were not captured"
    assert pseudo[":hover"]["color"] == "#fff"
    assert pseudo[":hover"]["background-color"] == "#333"
    assert ":focus" in pseudo


def test_cids_node_carries_pseudo_styles():
    resolver = CascadeResolver()
    soup, style_map = resolver.resolve(HOVER_HTML, "")
    root = HTMLToCidsParser.parse(soup, style_map, pseudo_map=resolver.pseudo_map)

    def find_btn(node: ComponentNode):
        if "btn" in node.attributes.get("class", ""):
            return node
        for c in node.children:
            f = find_btn(c)
            if f:
                return f
        return None

    btn = find_btn(root)
    assert btn is not None
    assert btn.pseudo_styles[":hover"]["color"] == "#fff"


def test_html_compiler_emits_pseudo_rules():
    resolver = CascadeResolver()
    soup, style_map = resolver.resolve(HOVER_HTML, "")
    root = HTMLToCidsParser.parse(soup, style_map, pseudo_map=resolver.pseudo_map)
    cids = CanonicalDesignSchema(url="http://x", root=root)

    html = HTMLCompiler().compile(cids)
    assert "<style>" in html
    assert ":hover" in html
    assert "wire-r1:hover" in html
    # The base element keeps its class and gains the generated one.
    assert "btn wire-r1" in html


def test_media_and_pseudo_share_one_generated_class():
    node = ComponentNode(
        tag="a",
        attributes={"class": "btn"},
        pseudo_styles={":hover": {"color": "#fff"}},
        responsive_styles={"@media (max-width: 600px)": {"display": "none"}},
    )
    cids = CanonicalDesignSchema(url="http://x", root=node)
    html = HTMLCompiler().compile(cids)
    # Exactly one generated class, referenced by both the pseudo and media rule.
    assert html.count("wire-r1") == 3  # class attr + :hover rule + media rule
    assert "wire-r2" not in html
