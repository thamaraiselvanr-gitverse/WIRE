import structlog
import hashlib

logger = structlog.get_logger(__name__)


class ConsensusValidator:
    """
    Quorum-based validation for reconstruction fidelity.
    Uses pairwise pixel-level comparison (VisualDiff) to evaluate consensus agreement.
    """

    def __init__(self, quorum_size: int = 3, threshold: float = 95.0):
        self.quorum_size = quorum_size
        self.threshold = threshold

    async def validate(self, renders: list[bytes]) -> dict:
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

        import tempfile
        import os
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
                        res = diff_engine.compare_screenshots(temp_files[i], temp_files[j])
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

