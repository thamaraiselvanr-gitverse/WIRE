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
