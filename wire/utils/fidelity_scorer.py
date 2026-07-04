from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class FidelityScorer:
    # Below this, the reconstruction is considered a critical failure even if
    # no exception was raised (e.g. a blank/broken page that rendered "successfully").
    CRITICAL_VISUAL_THRESHOLD = 40.0
    CRITICAL_STRUCTURAL_THRESHOLD = 40.0

    def __init__(self) -> None:
        self.critical_errors = 0
        self.non_critical_errors = 0
        self.base_score = 100.0
        self.visual_similarity: Optional[float] = None
        self.structural_similarity: Optional[float] = None

    def log_critical_error(
        self, message: str, context: Optional[Dict[str, Any]] = None
    ) -> None:
        self.critical_errors += 1
        logger.error(f"critical_fidelity_error: {message}", context=context)

    def log_non_critical_error(
        self, message: str, context: Optional[Dict[str, Any]] = None
    ) -> None:
        self.non_critical_errors += 1
        logger.warning(f"non_critical_fidelity_error: {message}", context=context)

    def record_visual_similarity(
        self, similarity_percent: float, context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Feed a real pixel/perceptual similarity score into the fidelity calc."""
        self.visual_similarity = similarity_percent
        logger.info(
            "visual_similarity_recorded", similarity=similarity_percent, context=context
        )
        if similarity_percent < self.CRITICAL_VISUAL_THRESHOLD:
            self.log_critical_error(
                f"Visual reconstruction diverges critically from original "
                f"({similarity_percent:.2f}% similarity)",
                context,
            )

    def record_structural_similarity(
        self, score: float, context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Feed a real DOM-structure comparison score into the fidelity calc."""
        self.structural_similarity = score
        logger.info("structural_similarity_recorded", score=score, context=context)
        if score < self.CRITICAL_STRUCTURAL_THRESHOLD:
            self.log_critical_error(
                f"Structural reconstruction diverges critically from original "
                f"({score:.2f}% match)",
                context,
            )

    def compute_score(self) -> float:
        if self.critical_errors > 0:
            return 0.0
        score = self.base_score - (self.non_critical_errors * 2.5)
        # Fidelity cannot exceed what was actually measured — an error-free run
        # that produced a visually/structurally divergent page is not "100%".
        if self.visual_similarity is not None:
            score = min(score, self.visual_similarity)
        if self.structural_similarity is not None:
            score = min(score, self.structural_similarity)
        return max(0.0, score)
