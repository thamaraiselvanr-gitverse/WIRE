"""Deep-mode behavioral capture: carousel autoplay timing and timed/exit-intent
triggers, exercised against a live fixture that actually animates and injects
content. Requires a Playwright browser."""

import pytest

from wire.agents.extraction.behavioral_extractor import BehavioralExtractor

# A page whose carousel mutates on a timer, injects a modal on mouse-leave, and
# grows the DOM while idle — so every deep branch has something to observe.
PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Deep</title></head>
<body>
  <div class="swiper"><div class="slide">1</div><div class="slide">2</div></div>
  <script>
    // Carousel autoplay: mutate the carousel on an interval.
    let i = 0;
    const sw = document.querySelector('.swiper');
    setInterval(() => {
      i++;
      sw.setAttribute('data-active', String(i % 2));
    }, 500);

    // Exit-intent: inject a dialog when the cursor leaves via the top.
    document.addEventListener('mouseleave', (e) => {
      if (e.clientY <= 0 && !document.querySelector('dialog[open]')) {
        const d = document.createElement('dialog');
        d.setAttribute('open', '');
        d.textContent = 'Wait!';
        document.body.appendChild(d);
      }
    });

    // Idle injection: keep adding nodes so the idle window (which opens only
    // after the 4s carousel observation) still sees the DOM growing.
    setInterval(() => {
      const el = document.createElement('div');
      el.className = 'late';
      document.body.appendChild(el);
    }, 400);
  </script>
</body></html>
"""


@pytest.mark.slow
@pytest.mark.asyncio
async def test_deep_behavioral_capture(tmp_path):
    from wire.agents.observation.browser_session import BrowserSession

    site = tmp_path / "site.html"
    site.write_text(PAGE, encoding="utf-8")

    session = BrowserSession()
    await session.start()
    try:
        page = await session.context.new_page()
        await page.goto("file://" + str(site), wait_until="load")
        report = await BehavioralExtractor().extract(page, deep=True)
        await page.close()
    finally:
        await session.stop()

    # Carousel timing was measured and autoplay detected.
    carousel = report["carousel_timing"]
    assert carousel["detected"] is True
    assert carousel["autoplay"] is True
    assert carousel["slide_changes_in_4s"] >= 1

    # Timed triggers: an exit-intent modal appeared and idle DOM growth was seen.
    timed = report["timed_triggers"]
    assert timed["exit_intent_modal"] is True
    assert timed["nodes_added_while_idle"] >= 1
