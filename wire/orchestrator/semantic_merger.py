from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class SemanticMerger:
    """
    Merges partial results from parallel workers into coherent output.
    For single-node Phase 3, this operates on in-memory dicts.
    """

    def merge_page_results(
        self, partial_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        logger.info("merging_partial_results", count=len(partial_results))
        merged: dict[str, Any] = {
            "pages": [],
            "assets": [],
            "interactions": [],
            "errors": [],
        }
        for result in partial_results:
            if "page" in result:
                merged["pages"].append(result["page"])
            if "assets" in result:
                merged["assets"].extend(result["assets"])
            if "interactions" in result:
                merged["interactions"].extend(result["interactions"])
            if "errors" in result:
                merged["errors"].extend(result["errors"])

        # Deduplicate assets by path
        seen = set()
        unique_assets = []
        for asset in merged["assets"]:
            if asset not in seen:
                seen.add(asset)
                unique_assets.append(asset)
        merged["assets"] = unique_assets

        logger.info(
            "merge_complete", pages=len(merged["pages"]), assets=len(merged["assets"])
        )
        return merged
