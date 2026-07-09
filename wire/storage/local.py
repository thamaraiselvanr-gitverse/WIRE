import os
import re
import urllib.parse
from typing import Optional

import structlog

from wire.storage.backend import StorageBackend
from wire.utils.config import get_config

logger = structlog.get_logger(__name__)

# Run directory names must be a single safe path segment.
_RUN_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_run_id(run_id: str) -> str:
    """Reduce a run id to one safe path segment (no traversal, no separators)."""
    cleaned = _RUN_ID_SAFE.sub("_", os.path.basename(run_id.strip()))
    return cleaned.strip("._") or "run"


class LocalStorage(StorageBackend):
    def __init__(self) -> None:
        self.config = get_config()
        self.base_dir = self.config.output_dir
        self.current_run_dir = ""

    def initialize_for_url(self, url: str, run_id: Optional[str] = None) -> None:
        """Create the run directory.

        When ``run_id`` is given (the platform passes ``project_<id>``), it
        names the directory — isolating runs per project so two users
        reconstructing the same domain never share or overwrite artifacts.
        Without it (CLI use), the directory falls back to the URL's domain.
        """
        if run_id:
            dirname = sanitize_run_id(run_id)
        else:
            parsed = urllib.parse.urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            if not domain:
                # Fallback for file:// or other empty-netloc URLs
                domain = os.path.basename(parsed.path) or "local"
                domain, _ = os.path.splitext(domain)
                if not domain:
                    domain = "local"
            dirname = domain.replace(":", "_")
        self.current_run_dir = os.path.join(self.base_dir, dirname)
        os.makedirs(self.current_run_dir, exist_ok=True)
        os.makedirs(self.get_asset_path(), exist_ok=True)
        logger.info("initialized_local_storage", directory=self.current_run_dir)

    def save_page(self, url: str, content: str) -> None:
        file_path = os.path.join(self.current_run_dir, "index.html")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("saved_page", path=file_path)

    def get_asset_path(self) -> str:
        if not self.current_run_dir:
            raise RuntimeError("Storage not initialized")
        return os.path.join(self.current_run_dir, "assets")
