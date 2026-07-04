import structlog

from wire.orchestrator.execution_router import ExecutionRouter
from wire.utils.logging import setup_logging


class WireService:
    def __init__(self) -> None:
        setup_logging()
        self.logger = structlog.get_logger(__name__)
        self.router = ExecutionRouter()

    async def run(self, url: str) -> float:
        self.logger.info("starting_wire_service", target_url=url)
        score = await self.router.execute_pipeline(url)
        return score
