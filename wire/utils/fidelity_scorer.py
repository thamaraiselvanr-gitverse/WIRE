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
        # Mean SSIM across validated responsive breakpoints (768/480), with
        # the per-breakpoint breakdown kept for reporting.
        self.responsive_visual_similarity: Optional[float] = None
        self.responsive_visual_breakdown: Dict[str, float] = {}

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

    def record_responsive_visual_similarity(
        self,
        breakpoint_scores: Dict[str, float],
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Feed per-breakpoint visual scores (e.g. tablet/mobile SSIM).

        The mean across breakpoints becomes an additional cap on the fidelity
        score: a reconstruction that only looks right at desktop width is not
        fully faithful. Unlike the desktop score, a low breakpoint score is
        not escalated to a critical error — catastrophic divergence is
        already caught by the desktop check.
        """
        valid = {k: float(v) for k, v in breakpoint_scores.items() if v is not None}
        if not valid:
            return
        self.responsive_visual_breakdown = valid
        self.responsive_visual_similarity = sum(valid.values()) / len(valid)
        logger.info(
            "responsive_visual_similarity_recorded",
            mean=round(self.responsive_visual_similarity, 2),
            breakdown=valid,
            context=context,
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
        if self.responsive_visual_similarity is not None:
            score = min(score, self.responsive_visual_similarity)
        return max(0.0, score)
