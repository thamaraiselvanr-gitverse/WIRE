from typing import Dict, List, Optional, Tuple

import structlog
from playwright.async_api import Page

logger = structlog.get_logger(__name__)


class ComputedStyleCapturer:
    """Capture browser-resolved computed styles for every rendered element.

    Re-deriving the CSS cascade from raw stylesheet text (``CascadeResolver``)
    is an inherently partial reimplementation: it approximates specificity,
    ignores ``!important``, and cannot resolve inheritance, ``var()`` or
    ``calc()`` the way the engine does. The browser has already computed the
    authoritative values, so this capturer reads ``getComputedStyle`` per
    element and keys the result by the same ``tag:nth-of-type`` selector path
    the CIDS parser derives, letting the pipeline prefer engine-resolved
    values over the heuristic cascade.

    Only properties whose value differs from a same-tag reference element's
    computed value are kept, so UA defaults and inherited values that a node
    did not actually change do not bloat the editable output.
    """

    # A generous, visually-meaningful superset. getComputedStyle returns fully
    # resolved longhands, so shorthands (e.g. ``background``) are read via their
    # component properties where the resolved form is what matters.
    CAPTURE_PROPERTIES: List[str] = [
        "color",
        "background-color",
        # NOTE: url()-bearing properties (background-image, mask, list-style
        # image) are deliberately excluded — getComputedStyle resolves them to
        # absolute origin URLs, which would leak the source host and fail to
        # load offline. Those come from the localized cascade instead.
        "background-size",
        "background-position",
        "background-repeat",
        "background-clip",
        "background-blend-mode",
        "font-family",
        "font-size",
        "font-weight",
        "font-style",
        "line-height",
        "letter-spacing",
        "text-align",
        "text-decoration",
        "text-transform",
        "text-shadow",
        "text-overflow",
        "white-space",
        "word-break",
        "overflow-wrap",
        "vertical-align",
        "writing-mode",
        "padding-top",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "margin-top",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "display",
        "flex-direction",
        "flex-wrap",
        "flex-grow",
        "flex-shrink",
        "flex-basis",
        "justify-content",
        "align-items",
        "align-content",
        "align-self",
        "gap",
        "row-gap",
        "column-gap",
        "grid-template-columns",
        "grid-template-rows",
        "grid-template-areas",
        "grid-column",
        "grid-row",
        "grid-area",
        "place-items",
        "place-content",
        "position",
        "top",
        "bottom",
        "left",
        "right",
        "width",
        "height",
        "min-width",
        "min-height",
        "max-width",
        "max-height",
        "box-sizing",
        "border-top-width",
        "border-right-width",
        "border-bottom-width",
        "border-left-width",
        "border-style",
        "border-color",
        "border-radius",
        "box-shadow",
        "opacity",
        "overflow-x",
        "overflow-y",
        "z-index",
        "object-fit",
        "object-position",
        "cursor",
        "list-style",
        "transform",
        "transform-origin",
        "transition",
        "filter",
        "backdrop-filter",
        "mix-blend-mode",
        "clip-path",
        "-webkit-clip-path",
        "outline-width",
        "outline-style",
        "outline-color",
        "outline-offset",
        "aspect-ratio",
        "visibility",
    ]

    # Responsive breakpoints to re-capture at, widest → narrowest so the
    # narrower rule is emitted later and wins where they overlap. Each entry is
    # ``(media_query, viewport_width)``.
    DEFAULT_BREAKPOINTS: List[Tuple[str, int]] = [
        ("@media (max-width: 768px)", 768),
        ("@media (max-width: 480px)", 480),
    ]

    async def capture(self, page: Page) -> Dict[str, Dict[str, str]]:
        """Return ``{selector_path: {property: computed_value}}`` for the page.

        Fails open (returns ``{}``) on any browser error so the pipeline can
        fall back to the heuristic cascade rather than aborting.
        """
        logger.info("capturing_computed_styles")
        try:
            raw = await page.evaluate(_CAPTURE_JS, self.CAPTURE_PROPERTIES)
        except Exception as e:  # pragma: no cover - defensive browser guard
            logger.warning("computed_style_capture_failed", error=str(e))
            return {}
        result: Dict[str, Dict[str, str]] = raw or {}
        logger.info("computed_styles_captured", elements=len(result))
        return result

    async def capture_responsive(
        self,
        page: Page,
        base_map: Dict[str, Dict[str, str]],
        breakpoints: Optional[List[Tuple[str, int]]] = None,
        base_size: Tuple[int, int] = (1920, 1080),
    ) -> Dict[str, Dict[str, Dict[str, str]]]:
        """Capture computed styles at each breakpoint width and return the deltas.

        For every breakpoint the viewport is narrowed and styles are re-captured;
        only properties whose computed value differs from the desktop ``base_map``
        become the breakpoint override. Result is
        ``{selector_path: {media_query: {property: value}}}`` — the engine-
        resolved counterpart to the cascade's ``@media`` parsing. The viewport is
        restored to ``base_size`` afterwards so downstream desktop captures are
        unaffected. Fails open to ``{}``.
        """
        breakpoints = breakpoints or self.DEFAULT_BREAKPOINTS
        responsive: Dict[str, Dict[str, Dict[str, str]]] = {}
        try:
            for media_query, width in breakpoints:
                await page.set_viewport_size({"width": width, "height": 900})
                bp_map = await self.capture(page)
                for path, props in bp_map.items():
                    base = base_map.get(path, {})
                    delta = {k: v for k, v in props.items() if base.get(k) != v}
                    if delta:
                        responsive.setdefault(path, {})[media_query] = delta
        except Exception as e:  # pragma: no cover - defensive browser guard
            logger.warning("responsive_computed_capture_failed", error=str(e))
        finally:
            await page.set_viewport_size(
                {"width": base_size[0], "height": base_size[1]}
            )
        logger.info("responsive_computed_captured", elements=len(responsive))
        return responsive


# Reads getComputedStyle for each rendered element, keeping only properties
# that differ from a freshly-created same-tag reference element (so UA defaults
# and unchanged inherited values are dropped). The path builder mirrors the
# Python CIDS parser's get_path exactly so the two maps key-align.
_CAPTURE_JS = """
(props) => {
    const out = {};
    const defaults = {};

    function refFor(tag) {
        if (defaults[tag] !== undefined) return defaults[tag];
        let snapshot = {};
        try {
            const el = document.createElement(tag);
            document.body.appendChild(el);
            const cs = getComputedStyle(el);
            props.forEach(p => { snapshot[p] = cs.getPropertyValue(p); });
            document.body.removeChild(el);
        } catch (e) {
            snapshot = {};
        }
        defaults[tag] = snapshot;
        return snapshot;
    }

    function getPath(node) {
        if (!node) return "";
        if (node.id) return '#' + CSS.escape(node.id);
        let path = [];
        while (node && node !== document.documentElement) {
            if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) break;
            let name = node.nodeName.toLowerCase();
            let sib = node, nth = 1;
            while (sib = sib.previousElementSibling) {
                if (sib.nodeName.toLowerCase() == name) nth++;
            }
            path.unshift(name + ":nth-of-type(" + nth + ")");
            node = node.parentNode;
        }
        return path.join(" > ");
    }

    const all = document.body ? document.body.querySelectorAll('*') : [];
    all.forEach(el => {
        const tag = el.nodeName.toLowerCase();
        if (["script", "style", "meta", "noscript", "link", "title", "head",
             "iframe", "object", "embed", "applet"].includes(tag)) return;
        const cs = getComputedStyle(el);
        const ref = refFor(tag);
        const styles = {};
        props.forEach(p => {
            const val = cs.getPropertyValue(p);
            if (val && val !== ref[p]) styles[p] = val;
        });
        if (Object.keys(styles).length) {
            const path = getPath(el);
            if (path) out[path] = styles;
        }
    });
    return out;
}
"""
