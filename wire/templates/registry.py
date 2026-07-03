import json
import os
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class TemplateRegistry:
    """Queryable template registry with semantic tags and rank-based ranking.

    Persists a JSON index so templates can be discovered by tag (all/any match)
    and ordered by a mutable rank. This is the relational layer of the hybrid
    relational + vector design described in the plan; a vector index can be
    layered on top without changing this contract.
    """

    def __init__(self, base_dir: str = "templates"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.index_path = os.path.join(self.base_dir, "registry.json")
        self.entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    self.entries = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.entries = []

    def _save(self) -> None:
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2, default=str)

    def register(
        self,
        template_id: str,
        url: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tags = tags or []
        metadata = metadata or {}
        # Replace any existing entry with the same id (idempotent re-register).
        self.entries = [e for e in self.entries if e["id"] != template_id]
        entry = {
            "id": template_id,
            "url": url,
            "tags": list(tags),
            "metadata": metadata,
            "rank": int(metadata.get("rank", 0)),
        }
        self.entries.append(entry)
        self._save()
        logger.info("template_registered", id=template_id, tags=tags)
        return entry

    def search_by_tags(
        self, tags: List[str], match_all: bool = False
    ) -> List[Dict[str, Any]]:
        query = set(tags)
        matched = []
        for entry in self.entries:
            entry_tags = set(entry.get("tags", []))
            if match_all:
                if query <= entry_tags:
                    matched.append(entry)
            elif query & entry_tags:
                matched.append(entry)
        matched.sort(key=lambda e: e.get("rank", 0), reverse=True)
        return matched

    def boost_rank(self, template_id: str, amount: int = 1) -> None:
        for entry in self.entries:
            if entry["id"] == template_id:
                entry["rank"] = entry.get("rank", 0) + amount
                self._save()
                logger.info("template_rank_boosted", id=template_id, rank=entry["rank"])
                return
        logger.warning("template_not_found_for_boost", id=template_id)

    def get(self, template_id: str) -> Optional[Dict[str, Any]]:
        return next((e for e in self.entries if e["id"] == template_id), None)

    def all(self) -> List[Dict[str, Any]]:
        return list(self.entries)
