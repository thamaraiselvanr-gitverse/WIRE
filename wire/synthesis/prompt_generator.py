import json
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger(__name__)


class PromptGenerator:
    """
    Generates AI-ready design prompts from CIDS and design architecture data.
    Produces LLM-friendly descriptions for design regeneration or variation.
    """

    def generate_prompts(
        self, design_data: Dict[str, Any], url: str
    ) -> List[Dict[str, Any]]:
        logger.info("generating_ai_design_prompts", url=url)

        prompts = []

        # Layout prompt
        prompts.append(
            {
                "id": "layout_reconstruction",
                "type": "layout",
                "prompt": self._build_layout_prompt(design_data, url),
            }
        )

        # Color scheme prompt
        prompts.append(
            {
                "id": "color_scheme",
                "type": "color",
                "prompt": self._build_color_prompt(design_data),
            }
        )

        # Typography prompt
        prompts.append(
            {
                "id": "typography_system",
                "type": "typography",
                "prompt": self._build_typography_prompt(design_data),
            }
        )

        # Full regeneration prompt
        prompts.append(
            {
                "id": "full_regeneration",
                "type": "full",
                "prompt": self._build_full_prompt(design_data, url),
            }
        )

        logger.info("prompts_generated", count=len(prompts))
        return prompts

    def _build_layout_prompt(self, data: Dict[str, Any], url: str) -> str:
        colors = data.get("colors", {})
        spacing = data.get("spacing", {})
        return (
            f"Recreate the layout structure of the webpage at {url}.\n"
            f"Apply the following design tokens:\n"
            f"- Colors: Primary={colors.get('primary', '#000')}, Background={colors.get('background', '#fff')}\n"
            f"- Spacing: sm={spacing.get('sm', '8px')}, md={spacing.get('md', '16px')}, lg={spacing.get('lg', '32px')}\n"
            f"Structure constraints:\n"
            f"- Organize content into a clear header, main section, grid of cards, and a footer.\n"
            f"- Identify and build reusable UI components (buttons, links, cards).\n"
            f"- Ensure layout is responsive (mobile-first, 768px and 1200px breakpoints)."
        )

    def _build_color_prompt(self, data: Dict[str, Any]) -> str:
        colors = data.get("colors", {})
        color_list = ", ".join([f"{k}: {v}" for k, v in colors.items()])
        return (
            f"Design a color system based on: {color_list}. "
            f"Generate complementary shades, tints, and semantic color tokens "
            f"(success, warning, error, info) that harmonize with this palette."
        )

    def _build_typography_prompt(self, data: Dict[str, Any]) -> str:
        typo = data.get("typography", {})
        return (
            f"Create a typography scale using base font '{typo.get('base', 'sans-serif')}' "
            f"and heading font '{typo.get('heading', 'serif')}'. "
            f"Define sizes for h1-h6, body, caption, and overline text. "
            f"Include line-height and letter-spacing recommendations."
        )

    def _build_full_prompt(self, data: Dict[str, Any], url: str) -> str:
        colors = data.get("colors", {})
        spacing = data.get("spacing", {})
        typography = data.get("typography", {})
        return (
            f"Fully reconstruct the web page at {url} using modern, clean, semantic HTML5 and CSS.\n"
            f"DESIGN SYSTEM GUIDELINES:\n"
            f"- Colors: {json.dumps(colors)}\n"
            f"- Typography: {json.dumps(typography)}\n"
            f"- Spacing: {json.dumps(spacing)}\n"
            f"SLOT BINDING CONTRACT:\n"
            f"- All text areas (headings, body) must be bound to dynamic string slots.\n"
            f"- All media elements (images, videos) must be mapped to asset source slots with alt attributes.\n"
            f"- Interactive components (buttons, toggles) must have empty handlers bound for future event injection.\n"
            f"OUTPUT REQUIREMENTS:\n"
            f"- Produce standalone HTML and a responsive CSS layout.\n"
            f"- Maintain visual parity with the original target and ensure full accessibility (WCAG AA standard)."
        )
