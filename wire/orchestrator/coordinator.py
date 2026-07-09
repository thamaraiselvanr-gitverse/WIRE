from typing import Any, Set

import structlog

logger = structlog.get_logger(__name__)


class Coordinator:
    """
    Redis-compatible coordination layer. Local in-memory lock manager for single node.
    """

    def __init__(self) -> None:
        self.locks: Set[Any] = set()

    def acquire_lock(self, resource_id: str) -> bool:
        if resource_id in self.locks:
            return False
        self.locks.add(resource_id)
        logger.debug("lock_acquired", resource=resource_id)
        return True

    def release_lock(self, resource_id: str) -> None:
        if resource_id in self.locks:
            self.locks.remove(resource_id)
            logger.debug("lock_released", resource=resource_id)
