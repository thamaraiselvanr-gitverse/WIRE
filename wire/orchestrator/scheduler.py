import structlog
import asyncio

logger = structlog.get_logger(__name__)

class TaskScheduler:
    """
    NUMA-aware task scheduling with single-node simulation.
    """
    def __init__(self):
        self.active_tasks = 0
        
    async def schedule(self, coro):
        logger.info("scheduling_task", active_tasks=self.active_tasks)
        self.active_tasks += 1
        try:
            return await coro
        finally:
            self.active_tasks -= 1
