"""Repeated inline styles are hoisted to shared classes in React and Vue too.

The same dedup the HTML compiler uses now applies to the React and Vue
adapters: identical style objects/bindings across nodes become a single
``wire-cls-N`` class in the emitted <style>, and the nodes wear the class
instead of repeating the inline style.
"""

from wire.compilers.react_adapter import ReactAdapter
from wire.compilers.vue_adapter import VueAdapter
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode


def _tree() -> CanonicalDesignSchema:
    def card(text: str) -> ComponentNode:
        return ComponentNode(
            tag="div",
            styles={"color": "rgb(34, 34, 34)", "padding": "16px"},
            text_content=text,
        )

    root = ComponentNode(
        tag="section",
        styles={"display": "grid"},  # unique -> stays inline
        children=[card("A"), card("B"), card("C")],
    )
    return CanonicalDesignSchema(url="http://x", root=root)


def test_react_dedup_promotes_repeats_and_keeps_uniques_inline():
    out = ReactAdapter().compile(_tree())
    # Shared class defined once, referenced by all three cards.
    assert ".wire-cls-1 { color: rgb(34, 34, 34); padding: 16px }" in out
    assert out.count('className="wire-cls-1"') == 3
    # The repeated inline style object is gone; the unique one remains.
    assert '"color": "rgb(34, 34, 34)"' not in out
    assert '"display": "grid"' in out


def test_vue_dedup_promotes_repeats_and_keeps_uniques_inline():
    out = VueAdapter().compile(_tree())
    assert ".wire-cls-1 { color: rgb(34, 34, 34); padding: 16px }" in out
    assert out.count('class="wire-cls-1"') == 3
    # The repeated inline binding is gone; the unique one remains.
    assert 'style="color: rgb(34, 34, 34); padding: 16px"' not in out
    assert 'style="display: grid"' in out


def test_react_no_dedup_when_nothing_repeats():
    root = ComponentNode(
        tag="div",
        children=[
            ComponentNode(tag="p", styles={"color": "red"}, text_content="a"),
            ComponentNode(tag="p", styles={"color": "blue"}, text_content="b"),
        ],
    )
    out = ReactAdapter().compile(CanonicalDesignSchema(url="http://x", root=root))
    assert "wire-cls" not in out
    assert '"color": "red"' in out and '"color": "blue"' in out


def test_dedup_merges_with_existing_class_in_react_and_vue():
    def span(text: str) -> ComponentNode:
        return ComponentNode(
            tag="span",
            attributes={"class": "label"},
            styles={"font-weight": "700"},
            text_content=text,
        )

    cids = CanonicalDesignSchema(
        url="http://x", root=ComponentNode(tag="div", children=[span("x"), span("y")])
    )
    react = ReactAdapter().compile(cids)
    vue = VueAdapter().compile(cids)
    assert 'className="label wire-cls-1"' in react
    assert 'class="label wire-cls-1"' in vue
