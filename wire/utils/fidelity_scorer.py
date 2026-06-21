import structlog

logger = structlog.get_logger(__name__)

class FidelityScorer:
    def __init__(self):
        self.critical_errors = 0
        self.non_critical_errors = 0
        self.base_score = 100.0

    def log_critical_error(self, message: str, context: dict = None):
        self.critical_errors += 1
        logger.error(f"critical_fidelity_error: {message}", context=context)

    def log_non_critical_error(self, message: str, context: dict = None):
        self.non_critical_errors += 1
        logger.warning(f"non_critical_fidelity_error: {message}", context=context)

    def compute_score(self) -> float:
        if self.critical_errors > 0:
            return 0.0
        return max(0.0, self.base_score - (self.non_critical_errors * 2.5))
