import copy
import json
import os
import re
from typing import Dict, Optional

import structlog

from wire.schema.canonical import ComponentNode

logger = structlog.get_logger(__name__)


class DesignTokenSystem:
    """Normalized, versioned design tokens with cross-template referencing.

    Enables applying one template's palette onto another template's layout by
    swapping matching token roles inside a CIDS subtree (e.g. Site A's colors on
    Site B's structure), preserving the original value's format (hex stays hex,
    rgb() stays rgb()).
    """

    def __init__(self, base_dir: str = "templates"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.tokens_path = os.path.join(self.base_dir, "tokens.json")
        self.store: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.tokens_path):
            try:
                with open(self.tokens_path, "r", encoding="utf-8") as f:
                    self.store = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.store = {}

    def _save(self) -> None:
        with open(self.tokens_path, "w", encoding="utf-8") as f:
            json.dump(self.store, f, indent=2, default=str)

    def save_tokens(self, template_id: str, tokens: dict) -> None:
        self.store[template_id] = tokens
        self._save()
        logger.info("design_tokens_saved", id=template_id)

    def get_tokens(self, template_id: str) -> Optional[dict]:
        return self.store.get(template_id)

    # ── color helpers ──
    @staticmethod
    def _to_rgb(value: str) -> Optional[tuple]:
        v = value.strip().lower()
        m = re.match(r"rgba?\(([^)]+)\)", v)
        if m:
            parts = [p.strip() for p in m.group(1).split(",")[:3]]
            try:
                return tuple(max(0, min(255, int(float(p)))) for p in parts)
            except (ValueError, TypeError):
                return None
        if v.startswith("#"):
            h = v[1:]
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            if len(h) == 6 and re.fullmatch(r"[0-9a-f]+", h):
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        return None

    @classmethod
    def _normalize_hex(cls, value: str) -> Optional[str]:
        rgb = cls._to_rgb(value)
        if rgb is None:
            return None
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    @classmethod
    def _reformat_like(cls, source_value: str, target_hex: str) -> str:
        """Render target_hex in the same format (hex vs rgb) as source_value."""
        rgb = cls._to_rgb(target_hex)
        if rgb is None:
            return target_hex
        if source_value.strip().lower().startswith("rgb"):
            return f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    @classmethod
    def _build_remap(cls, from_colors: dict, to_colors: dict) -> Dict[str, str]:
        """Map normalized source color -> target color, matched by token role."""
        remap = {}
        for role, src_val in from_colors.items():
            if role in to_colors:
                src_hex = cls._normalize_hex(src_val)
                dst_hex = cls._normalize_hex(to_colors[role])
                if src_hex and dst_hex:
                    remap[src_hex] = dst_hex
        return remap

    def swap_tokens_in_cids(
        self, node: ComponentNode, to_template_id: str, from_template_id: str
    ) -> ComponentNode:
        """Return a copy of ``node`` with ``from_template_id`` colors remapped to
        the corresponding ``to_template_id`` colors by shared token role."""
        src = (self.store.get(from_template_id) or {}).get("colors", {})
        dst = (self.store.get(to_template_id) or {}).get("colors", {})
        return self.apply_palette(node, {"colors": dst}, {"colors": src})

    def apply_palette(
        self, node: ComponentNode, to_tokens: dict, from_tokens: dict
    ) -> ComponentNode:
        """Return a copy of ``node`` with ``from_tokens`` colors remapped to the
        corresponding ``to_tokens`` colors (brand transfer), using explicit token
        dicts rather than stored ids. Value format is preserved per node."""
        remap = self._build_remap(
            (from_tokens or {}).get("colors", {}),
            (to_tokens or {}).get("colors", {}),
        )
        result = copy.deepcopy(node)
        self._apply_remap(result, remap)
        return result

    def _apply_remap(self, node: ComponentNode, remap: Dict[str, str]) -> None:
        for prop, value in list(node.styles.items()):
            norm = self._normalize_hex(value)
            if norm and norm in remap:
                node.styles[prop] = self._reformat_like(value, remap[norm])
        for child in node.children:
            self._apply_remap(child, remap)
        if node.shadow_root:
            self._apply_remap(node.shadow_root, remap)
