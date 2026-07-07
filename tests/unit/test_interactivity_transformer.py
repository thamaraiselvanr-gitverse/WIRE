"""Phase-3: JS-driven components restored as declarative CSS/HTML."""

from wire.compilers.html_compiler import HTMLCompiler
from wire.layout.interactivity_transformer import InteractivityTransformer
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode, DesignTokens


def _n(tag, attrs=None, text=None, children=None):
    node = ComponentNode(tag=tag, attributes=attrs or {}, children=children or [])
    if text is not None:
        node.children = [ComponentNode(tag="#text", text_content=text), *node.children]
    return node


def test_dropdown_gets_hover_reveal_css():
    root = _n(
        "nav",
        children=[
            _n(
                "li",
                attrs={"class": "menu-item-has-children"},
                children=[
                    _n("a", text="Products", attrs={"href": "/p"}),
                    _n(
                        "ul",
                        attrs={"class": "sub-menu"},
                        children=[_n("li", text="Item")],
                    ),
                ],
            )
        ],
    )
    out, report = InteractivityTransformer().transform(root)

    assert any(r.kind == "dropdown" for r in report.restored)
    assert report.injected_styles
    css = "\n".join(report.injected_styles)
    assert "display:none" in css
    assert ":hover>" in css and ":focus-within>" in css
    # Parent + submenu both wear generated classes.
    li = out.children[0]
    assert "wire-dd-1" in li.attributes["class"]
    submenu = li.children[1]
    assert "wire-dd-menu-1" in submenu.attributes["class"]


def test_dropdown_ignored_without_class_signal():
    # A plain nested list with no dropdown class is left untouched (avoids
    # hiding menus that were never dropdowns).
    root = _n("li", children=[_n("a", text="Home"), _n("ul", children=[_n("li")])])
    out, report = InteractivityTransformer().transform(root)
    assert report.restored == []
    assert "class" not in out.attributes


def test_original_tree_not_mutated():
    root = _n("li", attrs={"class": "dropdown"}, children=[_n("ul")])
    InteractivityTransformer().transform(root)
    assert root.attributes["class"] == "dropdown"  # no generated class leaked back


def test_aria_disclosure_becomes_details_summary():
    root = _n(
        "div",
        attrs={"class": "faq"},
        children=[
            _n(
                "button",
                text="Question 1",
                attrs={
                    "aria-expanded": "false",
                    "aria-controls": "a1",
                    "role": "button",
                },
            ),
            _n("div", attrs={"id": "a1"}, text="Answer 1"),
        ],
    )
    out, report = InteractivityTransformer().transform(root)

    assert any(r.kind == "disclosure" for r in report.restored)
    assert len(out.children) == 1
    details = out.children[0]
    assert details.tag == "details"
    assert "open" not in details.attributes  # aria-expanded=false -> collapsed
    assert details.children[0].tag == "summary"
    # aria-* / role are stripped from the summary.
    assert "aria-expanded" not in details.children[0].attributes
    assert details.children[1].attributes.get("id") == "a1"


def test_expanded_disclosure_is_open():
    root = _n(
        "div",
        children=[
            _n("h3", text="T", attrs={"aria-expanded": "true", "aria-controls": "p"}),
            _n("section", attrs={"id": "p"}, text="Panel"),
        ],
    )
    out, _ = InteractivityTransformer().transform(root)
    assert out.children[0].tag == "details"
    assert out.children[0].attributes.get("open") == "open"


def test_disclosure_without_matching_target_left_alone():
    root = _n(
        "div",
        children=[
            _n(
                "button",
                text="x",
                attrs={"aria-expanded": "false", "aria-controls": "missing"},
            ),
            _n("div", attrs={"id": "other"}, text="y"),
        ],
    )
    out, report = InteractivityTransformer().transform(root)
    assert report.restored == []
    assert out.children[0].tag == "button"


def test_aria_tabs_become_target_anchors():
    root = _n(
        "div",
        attrs={"class": "tabs"},
        children=[
            _n(
                "div",
                attrs={"role": "tablist"},
                children=[
                    _n(
                        "button",
                        text="One",
                        attrs={"role": "tab", "aria-controls": "p1"},
                    ),
                    _n(
                        "button",
                        text="Two",
                        attrs={"role": "tab", "aria-controls": "p2"},
                    ),
                ],
            ),
            _n("div", attrs={"role": "tabpanel", "id": "p1"}, text="Panel one"),
            _n("div", attrs={"role": "tabpanel", "id": "p2"}, text="Panel two"),
        ],
    )
    out, report = InteractivityTransformer().transform(root)

    assert any(r.kind == "tabs" for r in report.restored)
    assert "wire-tabgroup" in out.attributes["class"]
    tablist = out.children[0]
    # Tabs are now in-page anchors pointing at their panels.
    assert tablist.children[0].tag == "a"
    assert tablist.children[0].attributes["href"] == "#p1"
    assert tablist.children[1].attributes["href"] == "#p2"
    # Panels carry the switching class; the first is the default.
    assert "wire-tabpanel" in out.children[1].attributes["class"]
    assert "wire-tabpanel-first" in out.children[1].attributes["class"]
    css = "\n".join(report.injected_styles)
    assert ":target" in css and ":has(:target)" in css


def test_single_tab_is_not_transformed():
    root = _n(
        "div",
        children=[
            _n(
                "div",
                attrs={"role": "tablist"},
                children=[
                    _n(
                        "button",
                        text="Only",
                        attrs={"role": "tab", "aria-controls": "p1"},
                    )
                ],
            ),
            _n("div", attrs={"role": "tabpanel", "id": "p1"}, text="Solo"),
        ],
    )
    _out, report = InteractivityTransformer().transform(root)
    assert not any(r.kind == "tabs" for r in report.restored)


def test_carousel_becomes_scroll_snap_track():
    root = _n(
        "div",
        attrs={"class": "carousel"},
        children=[
            _n("div", attrs={"class": "slide"}, text="A"),
            _n("div", attrs={"class": "slide"}, text="B"),
            _n("div", attrs={"class": "slide"}, text="C"),
        ],
    )
    out, report = InteractivityTransformer().transform(root)
    assert any(r.kind == "carousel" for r in report.restored)
    assert "wire-carousel-1" in out.attributes["class"]
    css = "\n".join(report.injected_styles)
    assert "scroll-snap-type:x mandatory" in css
    assert "scroll-snap-align:start" in css


def test_carousel_applies_to_inner_track_when_present():
    root = _n(
        "div",
        attrs={"class": "swiper"},
        children=[
            _n(
                "div",
                attrs={"class": "swiper-wrapper"},
                children=[
                    _n("div", text="A"),
                    _n("div", text="B"),
                ],
            )
        ],
    )
    out, _ = InteractivityTransformer().transform(root)
    # The scroll-snap class lands on the inner wrapper (the real slide track).
    assert "wire-carousel-1" in out.children[0].attributes["class"]
    assert "wire-carousel" not in out.attributes.get("class", "")


def test_carousel_track_not_double_transformed():
    # Container transforms its inner track; revisiting the track must NOT
    # re-trigger on the injected "wire-carousel-" class (substring "carousel").
    root = _n(
        "div",
        attrs={"class": "carousel"},
        children=[
            _n(
                "div",
                attrs={"class": "slides"},
                children=[_n("div", text="A"), _n("div", text="B")],
            ),
            _n("div", text="C"),
        ],
    )
    _out, report = InteractivityTransformer().transform(root)
    assert sum(1 for r in report.restored if r.kind == "carousel") == 1


def test_carousel_needs_class_and_multiple_children():
    # A plain 2-child div (no carousel class) is left alone.
    root = _n("div", children=[_n("div", text="A"), _n("div", text="B")])
    _out, report = InteractivityTransformer().transform(root)
    assert not any(r.kind == "carousel" for r in report.restored)


def test_restored_components_render_valid_html():
    root = _n(
        "div",
        children=[
            _n(
                "li",
                attrs={"class": "has-dropdown"},
                children=[_n("a", text="Menu"), _n("ul", attrs={"class": "submenu"})],
            ),
            _n(
                "button",
                text="More",
                attrs={"aria-expanded": "true", "aria-controls": "d"},
            ),
            _n("div", attrs={"id": "d"}, text="Details body"),
        ],
    )
    out, report = InteractivityTransformer().transform(root)
    cids = CanonicalDesignSchema(
        url="https://ex.test",
        tokens=DesignTokens(),
        root=out,
        global_styles=report.injected_styles,
    )
    html = HTMLCompiler().compile_document(cids)
    assert "<details" in html and "<summary" in html
    assert "Details body" in html
    assert "wire-dd-menu-1" in html  # injected reveal CSS emitted
