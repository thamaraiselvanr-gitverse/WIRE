from typing import Any, Dict

import structlog

logger = structlog.get_logger(__name__)


class ConsensusValidator:
    """
    Render-agreement utility: measures how consistently a set of renders agree
    via pairwise pixel comparison (VisualDiff).

    NOTE: comparing repeated renders of the *same* URL only measures render
    determinism, not reconstruction fidelity — the pipeline now uses
    ``VisualDiff.volatility_mask`` for dynamic-region detection instead. This
    class remains a general-purpose agreement metric.
    """

    def __init__(self, quorum_size: int = 3, threshold: float = 95.0) -> None:
        self.quorum_size = quorum_size
        self.threshold = threshold

    async def validate(self, renders: list[bytes]) -> Dict[str, Any]:
        """
        Compare multiple renders of the same page using pairwise pixel comparison.
        Returns consensus result with agreement score.
        """
        logger.info("running_consensus_validation", renders=len(renders))

        if len(renders) < 2:
            return {
                "consensus": True,
                "agreement": 100.0,
                "renders": len(renders),
                "note": "Single render — consensus trivially satisfied",
                "comparison_method": "pixel-based (color delta)",
            }

        import os
        import tempfile

        from wire.validation.visual_diff import VisualDiff

        diff_engine = VisualDiff()
        temp_files = []

        try:
            # Save renders to temporary files
            for r in renders:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                tmp.write(r)
                tmp.close()
                temp_files.append(tmp.name)

            # Pairwise comparison
            similarities = []
            pair_details = []

            for i in range(len(temp_files)):
                for j in range(i + 1, len(temp_files)):
                    try:
                        res = diff_engine.compare_screenshots(
                            temp_files[i], temp_files[j]
                        )
                        sim = res["similarity_percent"]
                    except ValueError as e:
                        logger.warning("consensus_dimension_mismatch", error=str(e))
                        sim = 0.0
                    similarities.append(sim)
                    pair_details.append(f"render_{i}_vs_render_{j}: {sim}%")

            agreement = float(sum(similarities) / len(similarities))
            consensus = bool(agreement >= self.threshold)

            result = {
                "consensus": consensus,
                "agreement": round(agreement, 2),
                "renders": len(renders),
                "comparison_method": "pixel-based (color delta)",
                "threshold": self.threshold,
                "pair_details": pair_details,
            }

            logger.info(
                "consensus_result",
                consensus=result["consensus"],
                agreement=result["agreement"],
            )
            return result

        finally:
            # Clean up temp files
            for path in temp_files:
                try:
                    os.unlink(path)
                except OSError:
                    pass
