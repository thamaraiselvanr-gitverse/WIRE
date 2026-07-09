"""Engine-computed style capture and its authoritative merge into the CIDS."""

import pytest
from bs4 import BeautifulSoup

from wire.agents.observation.computed_style_capturer import ComputedStyleCapturer
from wire.schema.canonical import HTMLToCidsParser


class _FakePage:
    def __init__(self, result=None, raise_exc=False):
        self._result = result or {}
        self._raise = raise_exc
        self.evaluated_args = None

    async def evaluate(self, js, arg=None):
        if self._raise:
            raise RuntimeError("browser gone")
        self.evaluated_args = arg
        return self._result


@pytest.mark.asyncio
async def test_capture_returns_map_and_passes_property_list():
    page = _FakePage({"#hero": {"display": "flex"}})
    cap = ComputedStyleCapturer()
    out = await cap.capture(page)
    assert out == {"#hero": {"display": "flex"}}
    # The curated property list is handed to the browser evaluate call.
    assert "display" in page.evaluated_args
    assert "background-image" not in page.evaluated_args  # url() props excluded


@pytest.mark.asyncio
async def test_capture_fails_open_on_browser_error():
    cap = ComputedStyleCapturer()
    assert await cap.capture(_FakePage(raise_exc=True)) == {}


def test_node_path_id_shortcut_and_nth_of_type():
    soup = BeautifulSoup(
        "<html><body><section><div id='hero'>x</div>"
        "<div>a</div><div>b</div></section></body></html>",
        "lxml",
    )
    hero = soup.find("div", id="hero")
    assert HTMLToCidsParser.node_path(hero) == "#hero"

    second = soup.find_all("div")[2]  # the "b" div, 3rd div sibling
    path = HTMLToCidsParser.node_path(second)
    assert path == ("body:nth-of-type(1) > section:nth-of-type(1) > div:nth-of-type(3)")


def test_computed_styles_override_cascade_in_cids():
    soup = BeautifulSoup("<html><body><div id='hero'>hi</div></body></html>", "lxml")
    div = soup.find("div")
    root = HTMLToCidsParser.parse(
        soup,
        style_map={id(div): {"color": "red", "padding": "5px"}},
        computed_style_map={"#hero": {"color": "blue", "display": "flex"}},
    )
    hero = next(c for c in root.children if c.tag == "div")
    # Engine-computed value wins over the heuristic cascade for the same prop,
    # cascade-only props survive, and computed-only props are added.
    assert hero.styles["color"] == "blue"
    assert hero.styles["padding"] == "5px"
    assert hero.styles["display"] == "flex"


class _RespPage:
    """Fake page whose computed map depends on the current viewport width."""

    def __init__(self):
        self.width = 1920
        self.widths = []

    def _map(self):
        if self.width == 768:
            return {"#hero": {"color": "blue", "font-size": "14px"}}
        if self.width == 480:
            return {"#hero": {"color": "green", "font-size": "14px"}}
        return {"#hero": {"color": "red", "font-size": "16px"}}

    async def set_viewport_size(self, size):
        self.width = size["width"]
        self.widths.append(size["width"])

    async def evaluate(self, js, arg=None):
        return self._map()


@pytest.mark.asyncio
async def test_capture_responsive_returns_breakpoint_deltas_and_restores_viewport():
    page = _RespPage()
    cap = ComputedStyleCapturer()
    base = {"#hero": {"color": "red", "font-size": "16px"}}
    responsive = await cap.capture_responsive(page, base)

    tablet = responsive["#hero"]["@media (max-width: 768px)"]
    mobile = responsive["#hero"]["@media (max-width: 480px)"]
    assert tablet["color"] == "blue"
    assert tablet["font-size"] == "14px"
    assert mobile["color"] == "green"
    # Desktop viewport restored after capture so downstream shots stay desktop.
    assert page.widths[-1] == 1920


def test_computed_responsive_map_feeds_cids_responsive_styles():
    soup = BeautifulSoup("<html><body><div id='hero'>hi</div></body></html>", "lxml")
    root = HTMLToCidsParser.parse(
        soup,
        computed_responsive_map={
            "#hero": {"@media (max-width: 768px)": {"color": "blue"}}
        },
    )
    hero = next(c for c in root.children if c.tag == "div")
    assert hero.responsive_styles["@media (max-width: 768px)"]["color"] == "blue"


def test_computed_responsive_replaces_cascade_when_present():
    soup = BeautifulSoup("<html><body><div id='hero'>hi</div></body></html>", "lxml")
    div = soup.find("div")
    root = HTMLToCidsParser.parse(
        soup,
        responsive_map={id(div): {"@media (max-width: 900px)": {"color": "red"}}},
        computed_responsive_map={
            "#hero": {"@media (max-width: 768px)": {"color": "blue"}}
        },
    )
    hero = next(c for c in root.children if c.tag == "div")
    # Engine-resolved breakpoints win wholesale; the heuristic cascade @media
    # block for this node is not also emitted (no duplicate/conflicting rule).
    assert "@media (max-width: 768px)" in hero.responsive_styles
    assert "@media (max-width: 900px)" not in hero.responsive_styles


def test_computed_styles_absent_falls_back_to_cascade():
    soup = BeautifulSoup("<html><body><div id='hero'>hi</div></body></html>", "lxml")
    div = soup.find("div")
    root = HTMLToCidsParser.parse(
        soup,
        style_map={id(div): {"color": "red"}},
        computed_style_map={},  # no browser data -> cascade is authoritative
    )
    hero = next(c for c in root.children if c.tag == "div")
    assert hero.styles["color"] == "red"
