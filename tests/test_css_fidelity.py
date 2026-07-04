import os

import pytest

from wire.schema.canonical import HTMLToCidsParser
from wire.schema.style_mapper import CascadeResolver

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "fidelity_target.html"
)


def _normalize_color(c: str) -> str:
    c = str(c).lower().replace(" ", "")
    if c in ("rgb(255,0,0)", "red"):
        return "#ff0000"
    if c == "rgb(0,0,0)":
        return "#000000"
    if c == "rgb(51,51,51)":
        return "#333333"
    if c == "rgb(204,204,204)":
        return "#cccccc"
    if c == "rgb(187,187,187)":
        return "#bbbbbb"
    if c == "rgb(170,170,170)":
        return "#aaaaaa"
    if c == "rgb(68,68,68)":
        return "#444444"
    if c == "rgb(255,255,255)":
        return "#ffffff"
    return c


@pytest.fixture
def parsed_cids():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    resolver = CascadeResolver()
    soup, style_map = resolver.resolve(html, "")

    # We must start from HTML to ensure :root variables cascade down.
    # The parser starts from <body> by default; to evaluate <html> (and fetch
    # --brand-color) we explicitly run _process_node on the html node.
    html_node = soup.find("html")
    cids_root_fixed = HTMLToCidsParser._process_node(html_node, style_map)

    return cids_root_fixed, soup


@pytest.mark.asyncio
async def test_fidelity_parity(parsed_cids):
    cids_root, soup = parsed_cids

    def find_node_by_tag_and_text(node, tag, text=None):
        if node.tag == tag:
            if text is None:
                return node
            for c in node.children:
                if c.tag == "#text" and c.text_content and text in c.text_content:
                    return node
        for c in node.children:
            found = find_node_by_tag_and_text(c, tag, text)
            if found:
                return found
        return None

    # Test 1: Inheritance & Variables
    # The .box sets color: var(--brand-color, #000) which resolves to #ff0000
    # Nested span inherits this.
    span_node = find_node_by_tag_and_text(cids_root, "span", "Nested inherited text")
    assert span_node is not None, "Structural mismatch: span missing."
    assert (
        _normalize_color(span_node.styles.get("color", "")) == "#ff0000"
    ), f"Inheritance failed. Expected #ff0000, got {span_node.styles.get('color')}"

    # Test 2: Specificity ID > Class
    def find_div_special(n):
        if n.tag == "div" and n.attributes.get("id") == "special-box":
            return n
        for c in n.children:
            res = find_div_special(c)
            if res:
                return res
        return None

    special_box = find_div_special(cids_root)
    assert special_box is not None, "Special box not found"
    assert _normalize_color(special_box.styles.get("background-color", "")) == "#444444"

    # Test 3: Inline style overrides all
    p_node = find_node_by_tag_and_text(cids_root, "p", "Inline style text")
    assert p_node is not None
    assert _normalize_color(p_node.styles.get("color", "")) == "#ffffff"

    # Test 4: Structural pseudo-selector :first-child
    def find_li(n):
        if n.tag == "li" and n.attributes.get("id") == "list-1":
            return n
        for c in n.children:
            res = find_li(c)
            if res:
                return res
        return None

    li_node = find_li(cids_root)
    assert li_node is not None
    assert li_node.styles.get("font-weight") == "bold"
