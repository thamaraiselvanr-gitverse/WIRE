import json
import os
import shutil
import time
from typing import Any, Dict

import structlog

logger = structlog.get_logger(__name__)


class TemplateRepository:
    """
    Template repository for cached reconstructions.
    Stores completed site reconstructions as reusable templates
    for instant retrieval without re-crawling.
    """

    def __init__(self, repo_dir: str = "templates") -> None:
        self.repo_dir = repo_dir
        self.index_file = os.path.join(repo_dir, "index.json")
        os.makedirs(repo_dir, exist_ok=True)
        self._load_index()

    def _load_index(self) -> None:
        if os.path.exists(self.index_file):
            with open(self.index_file, "r", encoding="utf-8") as f:
                self.index = json.load(f)
        else:
            self.index = {"templates": {}}

    def _save_index(self) -> None:
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2)

    def store(self, url: str, source_dir: str, metadata: dict | None = None) -> str:
        """Cache a reconstruction as a template entry."""
        import hashlib

        template_id = hashlib.md5(url.encode()).hexdigest()[:12]
        template_dir = os.path.join(self.repo_dir, template_id)

        if os.path.exists(template_dir):
            shutil.rmtree(template_dir)
        shutil.copytree(source_dir, template_dir)

        self.index["templates"][template_id] = {
            "url": url,
            "created": time.time(),
            "metadata": metadata or {},
        }
        self._save_index()

        logger.info("template_stored", id=template_id, url=url)
        return template_id

    def retrieve(self, template_id: str) -> str | None:
        """Retrieve a cached template directory path."""
        if template_id not in self.index["templates"]:
            return None
        path = os.path.join(self.repo_dir, template_id)
        if os.path.exists(path):
            return path
        return None

    def list_templates(self) -> Dict[str, Any]:
        return self.index["templates"]
