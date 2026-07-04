import json
import os
import time
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class CheckpointManager:
    """
    TCP-style checkpointing for resumable crawls.
    Persists pipeline state to disk so that interrupted crawls
    can be resumed without data loss.
    """

    def __init__(self, checkpoint_dir: str) -> None:
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_file = os.path.join(checkpoint_dir, "checkpoint.json")
        os.makedirs(checkpoint_dir, exist_ok=True)

    def save(self, state: Dict[str, Any]) -> None:
        state["_timestamp"] = time.time()
        state["_version"] = 1
        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        logger.info("checkpoint_saved", file=self.checkpoint_file)

    def load(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.checkpoint_file):
            return None
        with open(self.checkpoint_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        logger.info(
            "checkpoint_loaded",
            file=self.checkpoint_file,
            timestamp=state.get("_timestamp"),
        )
        return state  # type: ignore[no-any-return]

    def mark_page_done(self, state: Dict[str, Any], url: str) -> Dict[str, Any]:
        if "completed_pages" not in state:
            state["completed_pages"] = []
        if url not in state["completed_pages"]:
            state["completed_pages"].append(url)
        self.save(state)
        return state

    def is_page_done(self, state: Dict[str, Any], url: str) -> bool:
        return url in state.get("completed_pages", [])

    def clear(self) -> None:
        if os.path.exists(self.checkpoint_file):
            os.remove(self.checkpoint_file)
            logger.info("checkpoint_cleared")
