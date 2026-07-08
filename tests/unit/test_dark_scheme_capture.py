"""Dark-scheme (prefers-color-scheme) computed-style capture as media deltas."""

import pytest

from wire.agents.observation.computed_style_capturer import ComputedStyleCapturer


class _FakePage:
    """Returns a light or dark style map depending on the emulated scheme."""

    def __init__(self, light_map, dark_map):
        self.light_map = light_map
        self.dark_map = dark_map
        self.scheme = "light"
        self.emulations = []

    async def emulate_media(self, color_scheme=None):
        self.scheme = color_scheme
        self.emulations.append(color_scheme)

    async def evaluate(self, script, arg=None):
        return self.dark_map if self.scheme == "dark" else self.light_map


LIGHT = {
    "body:nth-of-type(1)": {"color": "rgb(0, 0, 0)", "font-size": "16px"},
    "body:nth-of-type(1) > p:nth-of-type(1)": {"color": "rgb(20, 20, 20)"},
}
DARK = {
    "body:nth-of-type(1)": {"color": "rgb(255, 255, 255)", "font-size": "16px"},
    "body:nth-of-type(1) > p:nth-of-type(1)": {"color": "rgb(230, 230, 230)"},
}


@pytest.mark.asyncio
async def test_dark_deltas_keyed_under_prefers_color_scheme():
    cap = ComputedStyleCapturer()
    page = _FakePage(LIGHT, DARK)
    out = await cap.capture_color_scheme(page, LIGHT)

    q = ComputedStyleCapturer.DARK_SCHEME_QUERY
    assert q == "@media (prefers-color-scheme: dark)"
    # Only changed properties survive the diff: font-size is identical.
    assert out["body:nth-of-type(1)"][q] == {"color": "rgb(255, 255, 255)"}
    assert out["body:nth-of-type(1) > p:nth-of-type(1)"][q] == {
        "color": "rgb(230, 230, 230)"
    }


@pytest.mark.asyncio
async def test_page_without_dark_styles_yields_empty_map():
    cap = ComputedStyleCapturer()
    page = _FakePage(LIGHT, LIGHT)  # dark render identical to light
    out = await cap.capture_color_scheme(page, LIGHT)
    assert out == {}


@pytest.mark.asyncio
async def test_emulation_is_reset_to_light():
    cap = ComputedStyleCapturer()
    page = _FakePage(LIGHT, DARK)
    await cap.capture_color_scheme(page, LIGHT)
    assert page.emulations == ["dark", "light"]
    assert page.scheme == "light"


@pytest.mark.asyncio
async def test_capture_failure_fails_open_and_resets():
    cap = ComputedStyleCapturer()

    class _BrokenPage:
        def __init__(self):
            self.emulations = []

        async def emulate_media(self, color_scheme=None):
            self.emulations.append(color_scheme)

        async def evaluate(self, script, arg=None):
            raise RuntimeError("browser gone")

    page = _BrokenPage()
    out = await cap.capture_color_scheme(page, LIGHT)
    assert out == {}
    assert page.emulations == ["dark", "light"]  # still reset
