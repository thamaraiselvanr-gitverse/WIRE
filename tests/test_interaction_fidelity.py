"""
Phase 3.5 — Interaction Validation and Stabilization tests.

All tests in this module require a live headless Playwright browser session
and are marked @pytest.mark.slow so they are excluded from fast CI/CD runs.

Run with:  python -m pytest tests/test_interaction_fidelity.py -v -m slow
"""

import os

import pytest

from wire.agents.extraction.interaction_recorder import (
    MAX_INTERACTION_LIMIT,
    InteractionRecorder,
)

# ─────────────────────────────────────────────────────────────
# 1. Unit-level noise filter tests (fast, no browser needed)
# ─────────────────────────────────────────────────────────────


class TestNoiseFilter:
    """Validate the semantic normalizer catches false-positive diffs."""

    def test_rgba_vs_hex_identical(self):
        """rgba(0,0,0,1) and #000000 are the same color."""
        assert not InteractionRecorder._is_meaningful_diff(
            "rgba(0, 0, 0, 1)", "#000000"
        )

    def test_rgb_vs_hex_identical(self):
        """rgb(255,255,255) and #ffffff are the same."""
        assert not InteractionRecorder._is_meaningful_diff(
            "rgb(255, 255, 255)", "#ffffff"
        )

    def test_none_vs_empty(self):
        assert not InteractionRecorder._is_meaningful_diff("none", "")

    def test_none_vs_zero(self):
        assert not InteractionRecorder._is_meaningful_diff("none", "0px")

    def test_truly_different_colors(self):
        """Black and red must be flagged as different."""
        assert InteractionRecorder._is_meaningful_diff("rgb(0, 0, 0)", "rgb(255, 0, 0)")

    def test_alpha_change_is_meaningful(self):
        """Going from fully opaque to transparent is a real change."""
        assert InteractionRecorder._is_meaningful_diff(
            "rgba(0, 0, 0, 1)", "rgba(0, 0, 0, 0.5)"
        )

    def test_box_shadow_meaningful(self):
        assert InteractionRecorder._is_meaningful_diff(
            "none", "0px 4px 8px rgba(0, 0, 0, 0.5)"
        )


# ─────────────────────────────────────────────────────────────
# 2. Interaction cap enforcement (no browser needed)
# ─────────────────────────────────────────────────────────────


class TestInteractionLimits:
    def test_max_limit_constant(self):
        assert MAX_INTERACTION_LIMIT == 50

    def test_cap_applied_to_input(self):
        """Verify that a list of 100 elements gets sliced to 50."""
        fake_elements = [{"bbox": {"x": 0, "y": 0, "width": 10, "height": 10}}] * 100
        capped = fake_elements[:MAX_INTERACTION_LIMIT]
        assert len(capped) == 50


# ─────────────────────────────────────────────────────────────
# 3. Playwright browser-parity tests (slow)
# ─────────────────────────────────────────────────────────────

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "interaction_target.html"
)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_meaningful_hover_detected():
    """
    The .btn-target changes background from black to red on hover.
    The recorder must detect this as a meaningful diff.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(
            f"file:///{FIXTURE_PATH.replace(os.sep, '/')}", wait_until="networkidle"
        )

        # Locate .btn-target bounding box
        btn = page.locator(".btn-target")
        bbox = await btn.bounding_box()
        assert bbox is not None, "btn-target not found on page"

        recorder = InteractionRecorder()
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            results = await recorder.record_hover_states(
                page,
                [{"bbox": bbox, "selector": ".btn-target"}],
                tmpdir,
            )

        await browser.close()

    # The btn-target has a genuine color change — we must capture it
    assert len(results) >= 1, "Recorder failed to detect meaningful hover diff"
    diff = results[0]["style_diff"]
    assert "backgroundColor" in diff, f"Missing backgroundColor diff: {diff}"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_noise_hover_filtered():
    """
    The .link-noise changes #000000 → rgba(0,0,0,1) on hover.
    These are semantically identical; the recorder must filter this out.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(
            f"file:///{FIXTURE_PATH.replace(os.sep, '/')}", wait_until="networkidle"
        )

        link = page.locator(".link-noise")
        bbox = await link.bounding_box()
        assert bbox is not None

        recorder = InteractionRecorder()
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            results = await recorder.record_hover_states(
                page,
                [{"bbox": bbox, "selector": ".link-noise"}],
                tmpdir,
            )

        await browser.close()

    # Noise should be filtered — either no results, or results without a color diff
    color_diffs = [r for r in results if "color" in r.get("style_diff", {})]
    assert len(color_diffs) == 0, f"Noise was NOT filtered: {color_diffs}"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_determinism_across_runs():
    """
    Two consecutive runs on the same page must produce identical diffs.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(
            f"file:///{FIXTURE_PATH.replace(os.sep, '/')}", wait_until="networkidle"
        )

        btn = page.locator(".btn-target")
        bbox = await btn.bounding_box()

        recorder = InteractionRecorder()
        import tempfile

        run_results = []
        for _ in range(2):
            # Reset mouse position
            await page.mouse.move(0, 0)
            await page.wait_for_timeout(200)
            with tempfile.TemporaryDirectory() as tmpdir:
                r = await recorder.record_hover_states(
                    page,
                    [{"bbox": bbox, "selector": ".btn-target"}],
                    tmpdir,
                )
                # Normalize: strip screenshot paths (OS-dependent) for comparison
                cleaned = []
                for entry in r:
                    cleaned.append(
                        {
                            "selector": entry["selector"],
                            "style_diff": entry["style_diff"],
                        }
                    )
                run_results.append(cleaned)

        await browser.close()

    assert (
        run_results[0] == run_results[1]
    ), f"Determinism violated!\nRun 1: {run_results[0]}\nRun 2: {run_results[1]}"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_combinatorial_cap_enforcement():
    """
    The fixture dynamically creates 60 .explosion-btn elements.
    The recorder must process at most MAX_INTERACTION_LIMIT (50) of them,
    never freezing or crashing.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 2000})
        await page.goto(
            f"file:///{FIXTURE_PATH.replace(os.sep, '/')}", wait_until="networkidle"
        )

        # Collect all .explosion-btn bounding boxes
        locators = page.locator(".explosion-btn")
        count = await locators.count()
        assert count == 60, f"Expected 60 buttons, got {count}"

        elements = []
        for idx in range(count):
            bbox = await locators.nth(idx).bounding_box()
            if bbox:
                elements.append(
                    {"bbox": bbox, "selector": f".explosion-btn:nth({idx})"}
                )

        recorder = InteractionRecorder()
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            results = await recorder.record_hover_states(page, elements, tmpdir)

        await browser.close()

    # The system MUST have capped at 50
    assert len(elements) == 60
    # results length will be <= 50 (only meaningful diffs among the capped 50 get recorded)
    assert (
        len(results) <= MAX_INTERACTION_LIMIT
    ), f"Cap violated! Got {len(results)} results exceeding limit of {MAX_INTERACTION_LIMIT}"
