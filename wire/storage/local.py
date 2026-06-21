import os
import urllib.parse
from wire.storage.backend import StorageBackend
from wire.utils.config import get_config
import structlog

logger = structlog.get_logger(__name__)

class LocalStorage(StorageBackend):
    def __init__(self):
        self.config = get_config()
        self.base_dir = self.config.output_dir
        self.current_run_dir = ""

    def initialize_for_url(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        if not domain:
            # Fallback for file:// or other empty-netloc URLs
            domain = os.path.basename(parsed.path) or "local"
            domain, _ = os.path.splitext(domain)
            if not domain:
                domain = "local"
        domain = domain.replace(":", "_")
        self.current_run_dir = os.path.join(self.base_dir, domain)
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
