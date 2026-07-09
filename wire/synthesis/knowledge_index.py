import json
import os
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class KnowledgeIndex:
    """
    Queryable design knowledge database.
    Stores extracted design architecture — queryable by component, property, or pattern.
    Uses a simple JSON-backed index for Phase 4; ready for vector DB upgrade.
    """

    def __init__(self, index_dir: str = "output") -> None:
        self.index_dir = index_dir
        self.index_file = os.path.join(index_dir, "knowledge_index.json")
        self.entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.index_file):
            with open(self.index_file, "r", encoding="utf-8") as f:
                self.entries = json.load(f)

    def _save(self) -> None:
        os.makedirs(self.index_dir, exist_ok=True)
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2, default=str)

    def add_entry(self, url: str, category: str, key: str, value: Any) -> None:
        self.entries.append(
            {
                "url": url,
                "category": category,
                "key": key,
                "value": value,
            }
        )
        self._save()
        logger.info("knowledge_entry_added", category=category, key=key)

    def index_design(self, url: str, design_data: Dict[str, Any]) -> None:
        """Index all design tokens from a reconstructed site."""
        logger.info("indexing_design_knowledge", url=url)

        for category, tokens in design_data.items():
            if isinstance(tokens, dict):
                for key, value in tokens.items():
                    self.add_entry(url, category, key, value)
            else:
                self.add_entry(url, "misc", category, tokens)

    def query(
        self,
        category: Optional[str] = None,
        key: Optional[str] = None,
        token_match: Optional[str] = None,
        color_similarity_target: Optional[str] = None,
        color_similarity_threshold: float = 30.0,
    ) -> List[Dict[str, Any]]:
        """Query the knowledge index by category, key, token match, or color similarity."""
        results = self.entries
        if category:
            results = [e for e in results if e["category"] == category]
        if key:
            results = [e for e in results if e["key"] == key]
        if token_match:
            results = [
                e
                for e in results
                if token_match.lower() in str(e.get("value", "")).lower()
                or token_match.lower() in str(e.get("key", "")).lower()
            ]

        if color_similarity_target and (category == "colors" or not category):
            target_rgb = self._parse_hex_color(color_similarity_target)
            if target_rgb:
                matched_results = []
                for e in results:
                    val = e.get("value")
                    val_rgb = self._parse_hex_color(str(val))
                    if val_rgb:
                        dist = self._rgb_distance(target_rgb, val_rgb)
                        if dist <= color_similarity_threshold:
                            match_entry = e.copy()
                            match_entry["color_distance"] = round(dist, 2)
                            matched_results.append(match_entry)
                results = matched_results

        logger.info(
            "knowledge_query",
            category=category,
            key=key,
            token_match=token_match,
            results=len(results),
        )
        return results

    def _parse_hex_color(self, c: str) -> tuple[int, int, int] | None:
        if not isinstance(c, str):
            return None
        c = c.strip().lower()
        if c.startswith("#"):
            c = c[1:]
        if len(c) == 3:
            c = "".join([char * 2 for char in c])
        if len(c) == 6:
            try:
                return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
            except ValueError:
                return None
        return None

    def _rgb_distance(
        self, c1: tuple[int, int, int], c2: tuple[int, int, int]
    ) -> float:
        return (  # type: ignore[no-any-return]
            (c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2
        ) ** 0.5

    def query_by_url(self, url: str) -> List[Dict[str, Any]]:
        return [e for e in self.entries if e["url"] == url]
