from typing import Any

import structlog
from playwright.async_api import Page

logger = structlog.get_logger(__name__)

# Computed properties compared before/after an interaction to derive state deltas.
_STATE_PROPS = [
    "color",
    "background-color",
    "border-top-color",
    "box-shadow",
    "transform",
    "opacity",
    "text-decoration-line",
    "outline-width",
    "filter",
    "scale",
]

# In-browser detection of JS animation/interaction libraries and CSS animation
# markers — signals that a page has runtime behavior beyond static styling.
_LIBS_JS = r"""
() => {
  const w = window;
  const has = (g) => typeof w[g] !== 'undefined' && w[g] !== null;
  const q = (s) => document.querySelector(s);
  const libs = new Set();

  if (has('gsap') || has('TweenMax') || has('TweenLite')) libs.add('gsap');
  if (has('AOS') || q('[data-aos]')) libs.add('aos');
  if (has('Swiper') || q('.swiper, .swiper-container')) libs.add('swiper');
  if (has('lottie') || q('lottie-player, [class*="lottie"]')) libs.add('lottie');
  if (has('anime')) libs.add('anime.js');
  if (has('ScrollMagic')) libs.add('scrollmagic');
  if (has('THREE')) libs.add('three.js');
  if (has('Rellax') || q('[data-rellax-speed]')) libs.add('rellax');
  if (has('Typed')) libs.add('typed.js');
  if (has('particlesJS') || has('tsParticles')) libs.add('particles.js');
  if (q('[data-scroll], [data-scroll-container]')) libs.add('locomotive-scroll');
  if (q('[data-framer-name], [data-projectid]')) libs.add('framer-motion');
  if (has('VanillaTilt') || q('[data-tilt]')) libs.add('vanilla-tilt');
  if (q('.wow')) libs.add('wow.js');
  if (has('Alpine')) libs.add('alpine.js');

  const map = [
    ['gsap','gsap'],['aos','aos'],['swiper','swiper'],['lottie','lottie'],
    ['anime','anime.js'],['scrollmagic','scrollmagic'],['three','three.js'],
    ['locomotive','locomotive-scroll'],['rellax','rellax'],['typed','typed.js'],
    ['particles','particles.js'],['framer','framer-motion'],['tilt','vanilla-tilt'],
  ];
  Array.from(document.scripts).forEach(s => {
    const src = (s.src || '').toLowerCase();
    map.forEach(([k, name]) => { if (src.includes(k)) libs.add(name); });
  });

  const els = Array.from(document.querySelectorAll('*')).slice(0, 4000);
  let transitioning = 0, animated = 0;
  els.forEach(el => {
    const cs = getComputedStyle(el);
    const td = cs.transitionDuration || '';
    if (td && td !== '0s' && !/^0s(,\s*0s)*$/.test(td)) transitioning++;
    if (cs.animationName && cs.animationName !== 'none') animated++;
  });

  let scrollLinked = false;
  try {
    scrollLinked = document.getAnimations().some(
      a => a.timeline && /ScrollTimeline|ViewTimeline/.test(a.timeline.constructor.name)
    );
  } catch (e) { /* getAnimations unsupported */ }

  return {
    animation_libraries: Array.from(libs),
    scroll_markers: {
      data_aos: document.querySelectorAll('[data-aos]').length,
      wow: document.querySelectorAll('.wow').length,
      data_scroll: document.querySelectorAll('[data-scroll]').length,
      reveal: document.querySelectorAll('[class*="reveal"],[class*="animate-on-scroll"],[class*="fade-in"]').length,
    },
    transitioning_elements: transitioning,
    animated_elements: animated,
    scroll_linked_animations: scrollLinked,
    beforeunload_handler: typeof w.onbeforeunload === 'function',
  };
}
"""

# Snapshot opacity/transform of reveal candidates (used before/after scroll).
_SNAPSHOT_JS = r"""
() => {
  const els = Array.from(document.querySelectorAll(
    '[data-aos],[class*="reveal"],[class*="fade"],[class*="animate"],section,article,.card'
  )).slice(0, 300);
  return els.map((el, i) => {
    const cs = getComputedStyle(el);
    return { i, opacity: parseFloat(cs.opacity), transform: cs.transform };
  });
}
"""


class BehavioralExtractor:
    """Runtime behavioral capture that static analysis cannot reach.

    Drives the live page to detect JS animation libraries, per-component
    interaction-state deltas (real hover/focus computed-style diffs), and
    scroll-triggered reveals. In ``deep`` mode it also measures carousel
    autoplay intervals and detects timed / exit-intent triggers over short,
    bounded windows.
    """

    async def extract(self, page: Page, deep: bool = False) -> dict[str, Any]:
        logger.info("behavioral_extraction_started", deep=deep)
        report: dict[str, Any] = {}
        try:
            report.update(await page.evaluate(_LIBS_JS))
        except Exception as e:
            logger.warning("behavioral_libs_failed", error=str(e))
            report["error"] = str(e)

        report["interaction_states"] = await self._interaction_states(page)
        report["scroll_animations"] = await self._scroll_animations(page)

        if deep:
            report["carousel_timing"] = await self._carousel_timing(page)
            report["timed_triggers"] = await self._timed_triggers(page)

        logger.info(
            "behavioral_extraction_complete",
            libs=len(report.get("animation_libraries", [])),
            states=len(report.get("interaction_states", [])),
        )
        return report

    async def _computed(self, page: Page, selector: str) -> dict[str, Any]:
        try:
            result: dict[str, Any] = await page.eval_on_selector(
                selector,
                """(el, props) => {
                    const cs = getComputedStyle(el);
                    const out = {};
                    props.forEach(p => { out[p] = cs.getPropertyValue(p); });
                    return out;
                }""",
                _STATE_PROPS,
            )
            return result
        except Exception:
            return {}

    async def _interaction_states(self, page: Page) -> list[dict[str, Any]]:
        samples = [
            ("button", "button, .btn, [role='button'], a.button, .cta"),
            ("link", "nav a, main a, a"),
            ("input", "input:not([type='hidden']), textarea"),
        ]
        # A neutral parking spot for the cursor so the *base* read is never
        # taken while already hovering the target (the default cursor rests at
        # 0,0, which lands on a top-left CTA when the body has no margin).
        vp = page.viewport_size or {"width": 1280, "height": 720}
        neutral = (max(0, vp["width"] - 2), max(0, vp["height"] - 2))
        results: list[dict[str, Any]] = []
        for label, selector in samples:
            try:
                await page.mouse.move(*neutral)
                await page.wait_for_timeout(60)
            except Exception:
                pass
            base = await self._computed(page, selector)
            if not base:
                continue
            hover = base
            try:
                await page.hover(selector, timeout=1500)
                await page.wait_for_timeout(120)
                hover = await self._computed(page, selector)
            except Exception:
                pass
            focus = base
            try:
                await page.focus(selector, timeout=1500)
                await page.wait_for_timeout(80)
                focus = await self._computed(page, selector)
            except Exception:
                pass
            results.append(
                {
                    "component": label,
                    "hover_delta": self._delta(base, hover),
                    "focus_delta": self._delta(base, focus),
                }
            )
        return results

    @staticmethod
    def _delta(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        return {k: {"from": a[k], "to": b[k]} for k in a if k in b and a[k] != b[k]}

    async def _scroll_animations(self, page: Page) -> dict[str, Any]:
        try:
            before = await page.evaluate(_SNAPSHOT_JS)
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(700)
            after = await page.evaluate(_SNAPSHOT_JS)
            await page.evaluate("() => window.scrollTo(0, 0)")
        except Exception as e:
            logger.warning("scroll_animation_detection_failed", error=str(e))
            return {"revealed_on_scroll": 0, "error": str(e)}

        after_by_i = {row["i"]: row for row in after}
        revealed = 0
        for row in before:
            other = after_by_i.get(row["i"])
            if not other:
                continue
            became_visible = row["opacity"] < 0.5 <= other["opacity"]
            settled_transform = row["transform"] not in ("none", "") and other[
                "transform"
            ] in ("none", "matrix(1, 0, 0, 1, 0, 0)")
            if became_visible or settled_transform:
                revealed += 1
        return {"revealed_on_scroll": revealed, "candidates": len(before)}

    async def _carousel_timing(self, page: Page) -> dict[str, Any]:
        """Observe DOM mutations on carousels to infer autoplay + interval."""
        selector = ".swiper, [class*='carousel'], [class*='slider']"
        try:
            has_carousel = await page.query_selector(selector) is not None
        except Exception:
            has_carousel = False
        if not has_carousel:
            return {"detected": False}

        try:
            timestamps = await page.evaluate(
                """async (sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return [];
                    const ts = [];
                    const obs = new MutationObserver(() => ts.push(Date.now()));
                    obs.observe(el, {attributes:true, childList:true, subtree:true});
                    await new Promise(r => setTimeout(r, 4000));
                    obs.disconnect();
                    return ts;
                }""",
                selector,
            )
        except Exception as e:
            return {"detected": True, "error": str(e)}

        # Collapse near-simultaneous mutations, then measure gaps.
        events: list[int] = []
        for t in timestamps:
            if not events or t - events[-1] > 250:
                events.append(t)
        intervals = [events[i + 1] - events[i] for i in range(len(events) - 1)]
        autoplay = len(intervals) >= 1
        avg = round(sum(intervals) / len(intervals)) if intervals else None
        return {
            "detected": True,
            "autoplay": autoplay,
            "slide_changes_in_4s": len(events),
            "avg_interval_ms": avg,
        }

    async def _timed_triggers(self, page: Page) -> dict[str, Any]:
        """Detect exit-intent modals and idle/delayed injected content."""
        result: dict[str, Any] = {}

        # Exit-intent: simulate the cursor leaving via the top edge.
        try:
            before = await page.evaluate(
                '() => document.querySelectorAll(\'dialog[open],[role="dialog"],.modal.show,[class*="popup"]\').length'
            )
            await page.mouse.move(400, 300)
            await page.mouse.move(400, 0)
            await page.evaluate(
                "() => document.dispatchEvent(new MouseEvent('mouseleave', {clientY: -5}))"
            )
            await page.wait_for_timeout(800)
            after = await page.evaluate(
                '() => document.querySelectorAll(\'dialog[open],[role="dialog"],.modal.show,[class*="popup"]\').length'
            )
            result["exit_intent_modal"] = after > before
        except Exception:
            result["exit_intent_modal"] = False

        # Idle/delayed content: watch for DOM growth over a short idle window.
        try:
            n0 = await page.evaluate("() => document.querySelectorAll('*').length")
            await page.wait_for_timeout(2500)
            n1 = await page.evaluate("() => document.querySelectorAll('*').length")
            result["delayed_content_injected"] = n1 - n0 > 5
            result["nodes_added_while_idle"] = max(0, n1 - n0)
        except Exception:
            result["delayed_content_injected"] = False

        return result
