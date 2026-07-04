from typing import Any, Dict, List, Tuple

import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)


class StructuralValidator:
    """
    DOM structure comparison and semantic equivalence checking.

    Compares two HTML documents at the structural level. Children are aligned
    by a (tag, id, classes) signature using a longest-common-subsequence match
    rather than by raw index, so a single inserted or removed node does not
    cascade into misaligning every following sibling (which would otherwise
    drag the structural score — now a fidelity input — down artificially).
    """

    def _build_tree(self, html: str) -> Dict[str, Any]:
        """Build a simplified DOM tree representation."""
        soup = BeautifulSoup(html, "html.parser")

        def walk(node) -> dict | None:
            if node.name is None:
                return None
            children = []
            for child in node.children:
                if hasattr(child, "name") and child.name:
                    c = walk(child)
                    if c:
                        children.append(c)
            return {
                "tag": node.name,
                "id": node.get("id"),
                "classes": node.get("class", []),
                "children_count": len(children),
                "children": children,
            }

        body = soup.find("body")
        if body:
            return walk(body)
        return walk(soup)

    @staticmethod
    def _signature(node: Dict[str, Any]) -> Tuple[Any, ...]:
        """Identity signature used to align nodes across the two trees."""
        return (
            node["tag"],
            node.get("id"),
            tuple(sorted(node.get("classes", []) or [])),
        )

    @classmethod
    def _align_children(
        cls, orig_children: List[Any], recon_children: list
    ) -> List[Any]:
        """
        Longest-common-subsequence alignment of two child lists keyed by
        signature. Returns a list of (orig_or_None, recon_or_None) pairs:
        matched signatures pair up, insertions/deletions pair with None.
        """
        o_sigs = [cls._signature(c) for c in orig_children]
        r_sigs = [cls._signature(c) for c in recon_children]
        n, m = len(o_sigs), len(r_sigs)

        # Classic LCS dynamic-programming table.
        dp = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(n - 1, -1, -1):
            for j in range(m - 1, -1, -1):
                if o_sigs[i] == r_sigs[j]:
                    dp[i][j] = dp[i + 1][j + 1] + 1
                else:
                    dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])

        pairs = []
        i = j = 0
        while i < n and j < m:
            if o_sigs[i] == r_sigs[j]:
                pairs.append((orig_children[i], recon_children[j]))
                i += 1
                j += 1
            elif dp[i + 1][j] >= dp[i][j + 1]:
                pairs.append((orig_children[i], None))
                i += 1
            else:
                pairs.append((None, recon_children[j]))
                j += 1
        while i < n:
            pairs.append((orig_children[i], None))
            i += 1
        while j < m:
            pairs.append((None, recon_children[j]))
            j += 1
        return pairs

    def compare(self, original_html: str, reconstructed_html: str) -> Dict[str, Any]:
        logger.info("comparing_dom_structure")

        orig_tree = self._build_tree(original_html)
        recon_tree = self._build_tree(reconstructed_html)

        if orig_tree is None or recon_tree is None:
            return {"error": "Could not parse one or both documents", "score": 0.0}

        totals = {"nodes": 0, "matches": 0.0}

        def compare_nodes(orig: dict | None, recon: dict | None) -> None:
            # An unmatched node (present in only one tree) counts as a miss.
            if orig is None or recon is None:
                totals["nodes"] += 1
                return

            totals["nodes"] += 1
            if orig["tag"] == recon["tag"]:
                # Tag match is the baseline; matching id/classes refines the
                # score so structurally-identical-but-relabelled nodes rank
                # below true matches without being counted as total misses.
                score = 0.6
                if orig.get("id") == recon.get("id"):
                    score += 0.2
                if set(orig.get("classes") or []) == set(recon.get("classes") or []):
                    score += 0.2
                totals["matches"] += score

            for o_child, r_child in self._align_children(
                orig.get("children", []), recon.get("children", [])
            ):
                compare_nodes(o_child, r_child)

        compare_nodes(orig_tree, recon_tree)

        score = (totals["matches"] / max(totals["nodes"], 1)) * 100

        result = {
            "total_nodes_compared": totals["nodes"],
            "matching_nodes": round(totals["matches"], 2),
            "structural_score": round(score, 2),
        }

        logger.info("structural_comparison_complete", score=result["structural_score"])
        return result
