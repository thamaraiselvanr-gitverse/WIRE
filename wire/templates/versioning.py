import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class TemplateVersioning:
    """Delta-based version control for template CIDS trees.

    Stores full snapshots and computes flattened structural diffs (added /
    removed / changed paths) between any two versions, with rollback to a prior
    snapshot. Each version record wraps its payload under ``data``.
    """

    def __init__(self, base_dir: str = "templates") -> None:
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.store_path = os.path.join(self.base_dir, "versions.json")
        self.store: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    self.store = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.store = {}

    def _save(self) -> None:
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(self.store, f, indent=2, default=str)

    def save_version(self, template_id: str, data: Dict[str, Any]) -> int:
        versions = self.store.setdefault(template_id, [])
        version_number = len(versions) + 1
        versions.append(
            {
                "version": version_number,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data,
            }
        )
        self._save()
        logger.info("template_version_saved", id=template_id, version=version_number)
        return version_number

    def _record(self, template_id: str, version: int) -> Optional[Dict[str, Any]]:
        versions = self.store.get(template_id, [])
        if 1 <= version <= len(versions):
            return versions[version - 1]
        return None

    def get_version(self, template_id: str, version: int) -> Optional[Dict[str, Any]]:
        """Return the full version record (including its ``data`` payload)."""
        return self._record(template_id, version)

    def rollback(self, template_id: str, version: int) -> Optional[Dict[str, Any]]:
        """Return the raw CIDS payload of a prior version."""
        record = self._record(template_id, version)
        return record["data"] if record else None

    def diff(self, template_id: str, v1: int, v2: int) -> Dict[str, Any]:
        r1 = self._record(template_id, v1)
        r2 = self._record(template_id, v2)
        if not r1 or not r2:
            raise ValueError(f"Version not found for template '{template_id}'")

        f1 = self._flatten(self._root_of(r1["data"]))
        f2 = self._flatten(self._root_of(r2["data"]))

        added = {k: f2[k] for k in f2 if k not in f1}
        removed = {k: f1[k] for k in f1 if k not in f2}
        changed = {
            k: {"from": f1[k], "to": f2[k]} for k in f1 if k in f2 and f1[k] != f2[k]
        }

        return {
            "template_id": template_id,
            "from_version": v1,
            "to_version": v2,
            "details": {"added": added, "removed": removed, "changed": changed},
        }

    @staticmethod
    def _root_of(data: Dict[str, Any]) -> Dict[str, Any]:
        # Accept either a full schema ({"root": {...}}) or a bare node.
        if isinstance(data, dict) and "root" in data:
            return data["root"]  # type: ignore[no-any-return]
        return data

    def _flatten(self, node: Any, path: str = "root") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if not isinstance(node, dict):
            return out
        tag = node.get("tag", "?")
        node_key = f"{path}:{tag}"
        out[node_key] = tag
        for prop, value in (node.get("styles") or {}).items():
            out[f"{node_key}.styles.{prop}"] = value
        if node.get("text_content") is not None:
            out[f"{node_key}.text"] = node.get("text_content")
        for i, child in enumerate(node.get("children") or []):
            out.update(self._flatten(child, f"{node_key}/children[{i}]"))
        return out
