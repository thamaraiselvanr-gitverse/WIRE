import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)


class StructuralValidator:
    """
    DOM structure comparison and semantic equivalence checking.
    Compares two HTML documents at the structural level.
    """

    def _build_tree(self, html: str) -> dict:
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

    def compare(self, original_html: str, reconstructed_html: str) -> dict:
        logger.info("comparing_dom_structure")

        orig_tree = self._build_tree(original_html)
        recon_tree = self._build_tree(reconstructed_html)

        if orig_tree is None or recon_tree is None:
            return {"error": "Could not parse one or both documents", "score": 0.0}

        total_nodes = [0]
        matching_nodes = [0]

        def compare_nodes(orig: dict, recon: dict) -> None:
            total_nodes[0] += 1
            if orig["tag"] == recon["tag"]:
                matching_nodes[0] += 1

            orig_children = orig.get("children", [])
            recon_children = recon.get("children", [])

            for i in range(min(len(orig_children), len(recon_children))):
                compare_nodes(orig_children[i], recon_children[i])

            # Count unmatched children as misses
            total_nodes[0] += abs(len(orig_children) - len(recon_children))

        compare_nodes(orig_tree, recon_tree)

        score = (matching_nodes[0] / max(total_nodes[0], 1)) * 100

        result = {
            "total_nodes_compared": total_nodes[0],
            "matching_nodes": matching_nodes[0],
            "structural_score": round(score, 2),
        }

        logger.info("structural_comparison_complete", score=result["structural_score"])
        return result
