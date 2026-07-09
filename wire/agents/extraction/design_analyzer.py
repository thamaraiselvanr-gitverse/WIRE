import re
from collections import Counter
from typing import Any, Dict, Iterator, Optional, Tuple

import structlog
import tinycss2

logger = structlog.get_logger(__name__)


class DesignAnalyzer:
    """Extracts a design-token architecture (colors, typography, spacing) from CSS.

    Tokens are normalized (colors → hex, spacing → px), de-duplicated, and
    frequency-ranked so the most-used values surface as semantic tokens
    (``primary``/``background``, ``base``/``heading``, ``sm``/``md``/``lg``) that
    downstream consumers (``PromptGenerator``) actually read, with the full set
    preserved as an ordered scale.
    """

    _SPACING_PROPS = (
        "margin",
        "padding",
        "gap",
        "margin-top",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "padding-top",
        "padding-bottom",
        "padding-left",
        "padding-right",
    )

    def extract_design_architecture(
        self, html_content: str, css_content: str
    ) -> Dict[str, Any]:
        logger.info("extracting_design_architecture")

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "lxml")
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                css_content += "\n" + style_tag.string

        fg_colors: Counter[str] = Counter()
        bg_colors: Counter[str] = Counter()
        font_families: Counter[str] = Counter()
        font_sizes: Counter[float] = Counter()
        spacing_values: Counter[float] = Counter()

        for prop, val in self._iter_declarations(css_content):
            if prop in ("color", "border-color"):
                c = self._normalize_color(val)
                if c:
                    fg_colors[c] += 1
            elif prop in ("background-color", "background"):
                c = self._normalize_color(val)
                if c:
                    bg_colors[c] += 1
            elif prop == "font-family":
                fam = val.strip().strip("\"'")
                if fam:
                    font_families[fam] += 1
            elif prop == "font-size":
                px = self._to_px(val)
                if px is not None:
                    font_sizes[round(px, 2)] += 1
            elif prop in self._SPACING_PROPS:
                for token in val.split():
                    px = self._to_px(token)
                    if px is not None and px > 0:
                        spacing_values[round(px, 2)] += 1

        return {
            "colors": self._build_colors(fg_colors, bg_colors),
            "typography": self._build_typography(font_families, font_sizes),
            "spacing": self._build_spacing(spacing_values),
        }

    # ── declaration iteration (top-level + inside @media) ──
    def _iter_declarations(self, css_content: str) -> Iterator[Tuple[str, str]]:
        rules = tinycss2.parse_stylesheet(
            css_content, skip_comments=True, skip_whitespace=True
        )
        for rule in rules:
            rtype = getattr(rule, "type", None)
            if rtype == "qualified-rule":
                yield from self._decls_of(rule.content)
            elif (
                rtype == "at-rule"
                and getattr(rule, "lower_at_keyword", None) == "media"
                and rule.content is not None
            ):
                inner = tinycss2.parse_rule_list(
                    rule.content, skip_comments=True, skip_whitespace=True
                )
                for r in inner:
                    if getattr(r, "type", None) == "qualified-rule":
                        yield from self._decls_of(r.content)

    @staticmethod
    def _decls_of(content: Any) -> Iterator[Tuple[str, str]]:
        decls = tinycss2.parse_declaration_list(
            content, skip_comments=True, skip_whitespace=True
        )
        for decl in decls:
            if getattr(decl, "type", None) == "declaration":
                yield decl.lower_name, tinycss2.serialize(decl.value).strip()

    # ── normalization helpers ──
    @staticmethod
    def _normalize_color(val: str) -> Optional[str]:
        v = val.strip().lower()
        if not v:
            return None
        # rgb()/rgba() must be matched before any whitespace split (it contains
        # spaces, e.g. "rgb(255, 0, 0)"); match at the start to ignore trailing
        # shorthand tokens such as a background-image url().
        m = re.match(r"rgba?\(([^)]+)\)", v)
        if m:
            parts = [p.strip() for p in m.group(1).split(",")[:3]]
            try:
                r, g, b = (max(0, min(255, int(float(p)))) for p in parts)
                return f"#{r:02x}{g:02x}{b:02x}"
            except (ValueError, TypeError):
                return None
        # For hex / named colors only the leading token matters.
        tok = v.split()[0]
        if tok.startswith("#"):
            hexpart = tok[1:]
            if len(hexpart) == 3:
                hexpart = "".join(ch * 2 for ch in hexpart)
            if len(hexpart) in (6, 8) and re.fullmatch(r"[0-9a-f]+", hexpart):
                return "#" + hexpart[:6]
            return None
        # Named colors kept verbatim; skip clearly non-color keywords.
        if tok in {
            "inherit",
            "initial",
            "transparent",
            "none",
            "unset",
            "currentcolor",
        }:
            return None
        if re.fullmatch(r"[a-z]+", tok):
            return tok
        return None

    @staticmethod
    def _to_px(val: str) -> Optional[float]:
        m = re.match(r"^(-?\d*\.?\d+)\s*(px|rem|em)?$", val.strip().lower())
        if not m:
            return None
        num = float(m.group(1))
        unit = m.group(2) or "px"
        if unit in ("rem", "em"):
            return num * 16.0
        return num

    # ── token builders ──
    @staticmethod
    def _build_colors(fg: Counter[str], bg: Counter[str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        fg_ranked = [c for c, _ in fg.most_common()]
        bg_ranked = [c for c, _ in bg.most_common()]

        semantic_fg = ["primary", "secondary", "accent"]
        for name, color in zip(semantic_fg, fg_ranked):
            result[name] = color
        if bg_ranked:
            result["background"] = bg_ranked[0]

        # Remaining unique colors preserved as an ordered scale.
        seen = set(result.values())
        idx = 1
        for color in fg_ranked + bg_ranked:
            if color not in seen:
                result[f"color-{idx}"] = color
                seen.add(color)
                idx += 1

        if not result:
            result = {"primary": "#000000", "background": "#ffffff"}
        return result

    @staticmethod
    def _build_typography(
        families: Counter[str], sizes: Counter[float]
    ) -> Dict[str, str]:
        result: Dict[str, str] = {}
        fam_ranked = [f for f, _ in families.most_common()]
        if fam_ranked:
            result["base"] = fam_ranked[0]
        if len(fam_ranked) > 1:
            result["heading"] = fam_ranked[1]
        for i, fam in enumerate(fam_ranked[2:], start=1):
            result[f"font-{i}"] = fam

        # Ordered font-size scale (ascending), formatted back to px strings.
        for i, size in enumerate(sorted(sizes.keys()), start=1):
            result[f"size-{i}"] = f"{size:g}px"

        if not result:
            result = {"base": "Arial, sans-serif"}
        return result

    @staticmethod
    def _build_spacing(values: Counter[float]) -> Dict[str, str]:
        ordered = sorted(values.keys())
        result: Dict[str, str] = {}
        # Semantic names for the first few steps; consumers read sm/md/lg.
        semantic = ["xs", "sm", "md", "lg", "xl"]
        for name, px in zip(semantic, ordered):
            result[name] = f"{px:g}px"
        for i, px in enumerate(ordered[len(semantic) :], start=1):
            result[f"space-{i}"] = f"{px:g}px"

        if not result:
            result = {"sm": "8px", "md": "16px"}
        return result
