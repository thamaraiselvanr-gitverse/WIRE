import os
import re
from typing import Any, Dict, List

import structlog
from playwright.async_api import Page

logger = structlog.get_logger(__name__)

# Maximum number of interactions to evaluate per page
MAX_INTERACTION_LIMIT = 50


class InteractionRecorder:
    """
    Records hover, click, and scroll states as visual + CSS snapshots.
    Captures before/after screenshots for each interaction state.
    Applies semantic noise filtering to eliminate false-positive diffs.
    """

    @staticmethod
    def _normalize_css_value(value: str) -> str:
        """
        Normalize CSS values so that semantically identical representations
        (e.g. rgba(0,0,0,1) vs #000000, 'none' vs '') compare equal.
        """
        if not isinstance(value, str):
            return "none"

        val = value.strip().lower()

        # Normalize 'none' variants
        if val in ("none", "0px", "0", ""):
            return "none"

        # Normalize rgba(...) to hex
        rgba_match = re.match(
            r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)", val
        )
        if rgba_match:
            r, g, b = (
                int(rgba_match.group(1)),
                int(rgba_match.group(2)),
                int(rgba_match.group(3)),
            )
            a = float(rgba_match.group(4)) if rgba_match.group(4) else 1.0
            if a >= 0.999:
                return f"#{r:02x}{g:02x}{b:02x}"
            else:
                return f"rgba({r},{g},{b},{a:.2f})"

        return val

    @staticmethod
    def _is_meaningful_diff(before_val: str, after_val: str) -> bool:
        """Return True only if the before and after values are semantically different."""
        return InteractionRecorder._normalize_css_value(
            before_val
        ) != InteractionRecorder._normalize_css_value(after_val)

    async def record_hover_states(
        self, page: Page, hoverable_elements: List[Dict[str, Any]], asset_dir: str
    ) -> List[Dict[str, Any]]:
        capped = hoverable_elements[:MAX_INTERACTION_LIMIT]
        logger.info(
            "recording_hover_states",
            count=len(hoverable_elements),
            capped_to=len(capped),
        )
        results = []
        hover_dir = os.path.join(asset_dir, "interactions")
        os.makedirs(hover_dir, exist_ok=True)

        for i, element in enumerate(capped):
            bbox = element.get("bbox")
            if not bbox:
                continue
            try:
                # Get viewport size to prevent out-of-bounds clipping
                viewport = page.viewport_size
                vw, vh = (
                    (viewport["width"], viewport["height"])
                    if viewport
                    else (1920, 1080)
                )

                # Safe clip calculation
                clip_x = max(0, min(bbox["x"] - 10, vw - 1))
                clip_y = max(0, min(bbox["y"] - 10, vh - 1))
                clip_w = min(bbox["width"] + 20, vw - clip_x)
                clip_h = min(bbox["height"] + 20, vh - clip_y)

                if clip_w <= 0 or clip_h <= 0:
                    continue  # Skip invisible elements

                # Capture before state
                before_path = os.path.join(hover_dir, f"hover_{i}_before.png")
                await page.screenshot(
                    path=before_path,
                    clip={"x": clip_x, "y": clip_y, "width": clip_w, "height": clip_h},
                )

                # Get computed styles BEFORE hover
                js_before = await page.evaluate(
                    """
                    (pos) => {
                        const el = document.elementFromPoint(pos.x, pos.y);
                        if (!el) return null;
                        
                        function getPath(node) {
                            if (node.id) return '#' + CSS.escape(node.id);
                            let path = [];
                            while (node && node !== document.documentElement) {
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
                        
                        const s = getComputedStyle(el);
                        return {
                            path: getPath(el),
                            styles: {
                                backgroundColor: s.backgroundColor,
                                color: s.color,
                                transform: s.transform,
                                opacity: s.opacity,
                                boxShadow: s.boxShadow
                            }
                        };
                    }
                """,
                    {
                        "x": bbox["x"] + bbox["width"] / 2,
                        "y": bbox["y"] + bbox["height"] / 2,
                    },
                )

                if not js_before:
                    continue

                # Hover over element
                await page.mouse.move(
                    bbox["x"] + bbox["width"] / 2, bbox["y"] + bbox["height"] / 2
                )
                await page.wait_for_timeout(300)

                # Capture after state
                after_path = os.path.join(hover_dir, f"hover_{i}_after.png")
                await page.screenshot(
                    path=after_path,
                    clip={"x": clip_x, "y": clip_y, "width": clip_w, "height": clip_h},
                )

                # Get computed styles AFTER hover
                js_after_styles = await page.evaluate(
                    """
                    (pos) => {
                        const el = document.elementFromPoint(pos.x, pos.y);
                        if (!el) return {};
                        const s = getComputedStyle(el);
                        return {
                            backgroundColor: s.backgroundColor,
                            color: s.color,
                            transform: s.transform,
                            opacity: s.opacity,
                            boxShadow: s.boxShadow
                        };
                    }
                """,
                    {
                        "x": bbox["x"] + bbox["width"] / 2,
                        "y": bbox["y"] + bbox["height"] / 2,
                    },
                )

                # Compute semantically meaningful diff only
                diff = {}
                for k, v in js_after_styles.items():
                    before_v = js_before["styles"].get(k, "")
                    if self._is_meaningful_diff(before_v, v):
                        diff[k] = v

                if diff:
                    results.append(
                        {
                            "index": i,
                            "unique_path": js_before["path"],
                            "selector": element.get("selector"),
                            "before": f"interactions/hover_{i}_before.png",
                            "after": f"interactions/hover_{i}_after.png",
                            "style_diff": diff,
                        }
                    )
            except Exception as e:
                logger.warning("hover_recording_failed", index=i, error=str(e))

        logger.info("hover_states_recorded", count=len(results))
        return results
