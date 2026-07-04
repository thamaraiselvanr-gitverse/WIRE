"""Browser-backed test for runtime behavioral capture.

Drives a live fixture page to verify the BehavioralExtractor detects JS
animation libraries (via script src + DOM markers), real hover/focus
computed-style deltas, and scroll-triggered reveals. Requires a Playwright
browser (installed in CI via `playwright install chromium`).
"""

import pytest

from wire.agents.extraction.behavioral_extractor import BehavioralExtractor

# A page exercising every static/detectable behavioral signal:
#   - a fake gsap script src (library detection by src substring)
#   - [data-aos] + .swiper markers (library + scroll markers)
#   - a :hover color/transform change on the button (hover delta)
#   - a :focus outline change on the input (focus delta)
#   - a keyframe animation on .spin (animated_elements)
#   - a reveal element hidden until an IntersectionObserver fires on scroll
PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><title>Behavior</title>
<script src="https://cdn.example.test/gsap.min.js"></script>
<style>
  body { margin:0; font-family: Arial, sans-serif; }
  .cta {
    display:inline-block; background:#e0674f; color:#fff; padding:12px 20px;
    transition: background 0.2s, transform 0.2s;
  }
  .cta:hover { background:#c04a35; transform: scale(1.05); }
  input { outline: 1px solid #ccc; transition: outline 0.2s; }
  input:focus { outline: 3px solid #2b6cb0; }
  @keyframes spin { from {transform:rotate(0)} to {transform:rotate(360deg)} }
  .spin { animation: spin 2s linear infinite; }
  .spacer { height: 1600px; }
  .reveal {
    opacity: 0; transform: translateY(40px);
    transition: opacity 0.3s, transform 0.3s;
  }
  .reveal.shown { opacity: 1; transform: none; }
</style></head>
<body>
  <header>
    <a class="cta" href="#go">Get started</a>
    <input type="text" aria-label="email">
  </header>
  <div class="swiper" data-aos="fade-up"><div>slide</div></div>
  <div class="spin">o</div>
  <div class="spacer"></div>
  <section class="reveal" id="rev"><h2>Revealed on scroll</h2></section>
  <script>
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => { if (e.isIntersecting) e.target.classList.add('shown'); });
    });
    io.observe(document.getElementById('rev'));
  </script>
</body></html>
"""


@pytest.mark.slow
@pytest.mark.asyncio
async def test_behavioral_capture(tmp_path):
    from wire.agents.observation.browser_session import BrowserSession

    site = tmp_path / "site.html"
    site.write_text(PAGE, encoding="utf-8")

    session = BrowserSession()
    await session.start()
    try:
        page = await session.context.new_page()
        await page.goto("file://" + str(site), wait_until="networkidle")
        report = await BehavioralExtractor().extract(page, deep=False)
        await page.close()
    finally:
        await session.stop()

    # Library detection: gsap via <script src>, aos + swiper via DOM markers.
    libs = report["animation_libraries"]
    assert "gsap" in libs
    assert "aos" in libs
    assert "swiper" in libs

    # CSS animation / transition inventory.
    assert report["animated_elements"] >= 1
    assert report["transitioning_elements"] >= 1

    # Scroll markers.
    assert report["scroll_markers"]["data_aos"] >= 1

    # Interaction-state deltas: the button changes on hover, the input on focus.
    states = {s["component"]: s for s in report["interaction_states"]}
    button = states.get("button")
    assert button is not None
    assert button["hover_delta"], "expected a hover computed-style change"
    changed = set(button["hover_delta"])
    assert "background-color" in changed or "transform" in changed

    input_state = states.get("input")
    assert input_state is not None
    assert input_state["focus_delta"], "expected a focus computed-style change"

    # Scroll-triggered reveal: the .reveal section fades/settles in on scroll.
    assert report["scroll_animations"]["revealed_on_scroll"] >= 1
