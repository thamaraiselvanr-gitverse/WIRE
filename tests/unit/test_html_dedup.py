"""Inline-style deduplication in the HTML compiler.

Repeated identical inline styles are hoisted into shared ``wire-cls-N`` classes
in the <style> block; unique one-off styles stay inline. This keeps the editable
output lean without changing how it renders.
"""

from wire.compilers.html_compiler import HTMLCompiler
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode


def _card(text: str) -> ComponentNode:
    # Three cards share an identical style string -> should be deduped.
    return ComponentNode(
        tag="div",
        styles={"color": "rgb(34, 34, 34)", "padding": "16px"},
        text_content=text,
    )


def _tree() -> CanonicalDesignSchema:
    root = ComponentNode(
        tag="section",
        styles={"display": "grid", "gap": "24px"},  # unique -> stays inline
        children=[_card("A"), _card("B"), _card("C")],
    )
    return CanonicalDesignSchema(url="http://x", root=root)


def test_repeated_styles_become_a_shared_class():
    html = HTMLCompiler().compile(_tree())

    # The shared style is defined once as a class and the inline copies are gone.
    assert ".wire-cls-1 { color: rgb(34, 34, 34); padding: 16px }" in html
    assert html.count('style="color: rgb(34, 34, 34); padding: 16px"') == 0
    # All three cards reference the class.
    assert html.count('class="wire-cls-1"') == 3


def test_unique_style_stays_inline():
    html = HTMLCompiler().compile(_tree())
    # The one-off section style is not promoted; it remains inline.
    assert 'style="display: grid; gap: 24px"' in html
    assert "wire-cls" not in html.split("<section")[1].split(">")[0]


def test_no_dedup_when_nothing_repeats():
    root = ComponentNode(
        tag="div",
        children=[
            ComponentNode(tag="p", styles={"color": "red"}, text_content="a"),
            ComponentNode(tag="p", styles={"color": "blue"}, text_content="b"),
        ],
    )
    html = HTMLCompiler().compile(CanonicalDesignSchema(url="http://x", root=root))
    assert "wire-cls" not in html
    assert 'style="color: red"' in html
    assert 'style="color: blue"' in html


def test_dedup_merges_with_existing_class_attribute():
    node = ComponentNode(
        tag="span",
        attributes={"class": "label"},
        styles={"font-weight": "700"},
        text_content="x",
    )
    node2 = ComponentNode(
        tag="span",
        attributes={"class": "label"},
        styles={"font-weight": "700"},
        text_content="y",
    )
    root = ComponentNode(tag="div", children=[node, node2])
    html = HTMLCompiler().compile(CanonicalDesignSchema(url="http://x", root=root))
    # Author class preserved and the generated class appended alongside it.
    assert 'class="label wire-cls-1"' in html
    assert html.count("wire-cls-1") == 3  # 2 usages + 1 definition
