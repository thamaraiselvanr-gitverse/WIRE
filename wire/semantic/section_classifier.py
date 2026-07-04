"""
Section Classifier — General-Purpose Website Section Classification.

Classifies CIDS subtrees into known content roles using a two-tier
approach: heuristic fast-path for structurally certain patterns,
LLM fallback for ambiguous cases. The taxonomy is intentionally
general-purpose (site-type agnostic).
"""

from typing import List, Optional, Tuple

import structlog

from wire.schema.canonical import ComponentNode
from wire.schema.semantic_schema import (
    CLASSIFICATION_CONFIDENCE_THRESHOLD,
    ClassifiedSection,
    SectionRole,
)
from wire.semantic.llm_guard import LLMGuard

logger = structlog.get_logger(__name__)

# Block-level elements that indicate section-level structure
SECTION_LEVEL_TAGS = {
    "div",
    "section",
    "header",
    "footer",
    "nav",
    "main",
    "aside",
    "article",
    "form",
}

# Repeatable-shaped roles that may have multiple instances
REPEATABLE_ROLES = {
    SectionRole.PORTFOLIO,
    SectionRole.TEAM,
    SectionRole.TESTIMONIALS,
    SectionRole.PRICING,
    SectionRole.FEATURE_GRID,
}

# ── Heuristic Pattern Definitions ───────────────────────────────────────
# Each entry: (patterns_to_match, SectionRole, confidence)
# Confidence is deliberately calibrated per-pattern — only patterns with
# genuine structural certainty claim >= 0.80.

_CLASS_ID_PATTERNS: list[tuple[list[str], SectionRole, float]] = [
    (
        ["contact", "contact-us", "get-in-touch", "contact_us", "contactus"],
        SectionRole.CONTACT,
        0.85,
    ),
    (
        [
            "testimonial",
            "review",
            "client-say",
            "client_say",
            "reviews",
            "testimonials",
        ],
        SectionRole.TESTIMONIALS,
        0.85,
    ),
    (
        ["pricing", "price", "plan", "plans", "pricing-table", "pricing_table"],
        SectionRole.PRICING,
        0.85,
    ),
    (["team", "our-team", "staff", "our_team", "members"], SectionRole.TEAM, 0.85),
    (["faq", "frequently-asked", "faqs", "frequently_asked"], SectionRole.FAQ, 0.85),
    (
        ["blog", "news", "articles", "posts", "blog-feed", "blog_feed"],
        SectionRole.BLOG_FEED,
        0.80,
    ),
    (
        [
            "portfolio",
            "work",
            "projects",
            "gallery",
            "our-work",
            "our_work",
            "showcase",
        ],
        SectionRole.PORTFOLIO,
        0.80,
    ),
    (
        ["service", "services", "what-we-do", "what_we_do", "offerings"],
        SectionRole.SERVICES,
        0.80,
    ),
    (
        ["about", "about-us", "who-we-are", "about_us", "who_we_are"],
        SectionRole.ABOUT,
        0.80,
    ),
    (
        ["feature", "features", "feature-grid", "feature_grid"],
        SectionRole.FEATURE_GRID,
        0.80,
    ),
    (["cta", "call-to-action", "call_to_action"], SectionRole.CTA, 0.80),
    (
        ["social", "social-media", "social-links", "social_links", "social_media"],
        SectionRole.SOCIAL_LINKS,
        0.80,
    ),
    (
        ["hero", "banner", "jumbotron", "hero-section", "hero_section", "masthead"],
        SectionRole.HERO,
        0.90,
    ),
    (
        ["media-gallery", "media_gallery", "image-gallery", "photo-gallery"],
        SectionRole.MEDIA_GALLERY,
        0.80,
    ),
    (["sidebar", "side-bar", "side_bar"], SectionRole.SIDEBAR, 0.85),
]


class SectionClassifier:
    """
    Classifies CIDS subtrees into known content roles.

    Two-tier classification:
    1. Heuristic fast-path: tag structure, class names, ARIA roles, content patterns.
       If confidence >= 0.80 AND match is structurally certain, returns without LLM.
    2. LLM fallback: for ambiguous subtrees. Output constrained to
       {section_role, confidence, reasoning} via llm_guard.

    Sections below 0.80 confidence → UNKNOWN, never forced into a category.
    """

    def __init__(self, llm_guard: LLMGuard):
        self.llm_guard = llm_guard

    def classify_tree(self, root: ComponentNode) -> List[ClassifiedSection]:
        """
        Walk the CIDS tree and classify top-level sections.

        Identifies section-level nodes (direct children of root that are
        block-level elements) and classifies each.
        """
        classifications: List[ClassifiedSection] = []

        for idx, child in enumerate(root.children):
            if child.tag not in SECTION_LEVEL_TAGS and child.tag != "#text":
                continue
            if child.tag == "#text":
                continue

            node_path = f"root > {child.tag}:nth-child({idx + 1})"
            classified = self._classify_node(child, node_path)
            classifications.append(classified)

        # Detect repeat patterns for repeatable roles
        self._enrich_repeat_counts(root, classifications)

        logger.info(
            "section_classifier_tree_complete",
            total_sections=len(classifications),
            classified=[c.section_role.value for c in classifications],
        )
        return classifications

    def _classify_node(self, node: ComponentNode, node_path: str) -> ClassifiedSection:
        """Classify a single section-level node."""
        role, confidence, reasoning = self._heuristic_classify(node)

        if confidence >= CLASSIFICATION_CONFIDENCE_THRESHOLD:
            result = ClassifiedSection(
                node_path=node_path,
                section_role=role,
                confidence=confidence,
                reasoning=reasoning,
                is_heuristic=True,
                child_count=len(node.children),
            )
            logger.info(
                "section_classified_heuristic",
                path=node_path,
                role=role.value,
                confidence=confidence,
            )
            return result

        # LLM fallback for ambiguous nodes
        return self._llm_classify(node, node_path)

    def _heuristic_classify(
        self, node: ComponentNode
    ) -> Tuple[SectionRole, float, str]:
        """
        Heuristic classification based on tag, class, id, and ARIA roles.

        Returns (role, confidence, reasoning). Confidence scores are
        deliberately calibrated per-pattern — only patterns with genuine
        structural certainty claim >= 0.80.
        """
        tag = node.tag.lower()

        # Tag-level structural certainty
        if tag == "nav":
            return SectionRole.NAVIGATION, 0.95, "Structural <nav> tag"
        if tag == "footer":
            return SectionRole.FOOTER, 0.95, "Structural <footer> tag"
        if tag == "aside":
            return SectionRole.SIDEBAR, 0.85, "Structural <aside> tag"

        # Header tag with hero-like indicators
        if tag == "header":
            classes = self._get_classes(node)
            hero_keywords = {"hero", "banner", "jumbotron", "masthead"}
            if any(kw in cls.lower() for cls in classes for kw in hero_keywords):
                return (
                    SectionRole.HERO,
                    0.90,
                    f"<header> tag with hero-class: {classes}",
                )
            return (
                SectionRole.HERO,
                0.80,
                "Structural <header> tag (likely hero/banner)",
            )

        # ARIA role-based classification
        aria_role = node.attributes.get("role", "").lower()
        if aria_role == "navigation":
            return SectionRole.NAVIGATION, 0.90, "ARIA role='navigation'"
        if aria_role == "contentinfo":
            return SectionRole.FOOTER, 0.85, "ARIA role='contentinfo'"
        if aria_role == "banner":
            return SectionRole.HERO, 0.85, "ARIA role='banner'"
        if aria_role == "complementary":
            return SectionRole.SIDEBAR, 0.80, "ARIA role='complementary'"

        # Class/ID pattern matching
        classes = self._get_classes(node)
        node_id = node.attributes.get("id", "").lower()
        all_identifiers = classes + ([node_id] if node_id else [])

        for patterns, role, conf in _CLASS_ID_PATTERNS:
            for identifier in all_identifiers:
                for pattern in patterns:
                    if pattern in identifier:
                        return (
                            role,
                            conf,
                            f"Class/ID match: '{identifier}' contains '{pattern}'",
                        )

        # No match — return UNKNOWN
        return SectionRole.UNKNOWN, 0.0, "No heuristic match found"

    def _llm_classify(self, node: ComponentNode, node_path: str) -> ClassifiedSection:
        """
        LLM fallback classification for ambiguous nodes.

        Uses llm_guard.call_classification() for live LLM calls when a
        client is wired. Falls back to UNKNOWN when no client is
        available or the call fails (fail-closed).
        """
        # Attempt live LLM classification via the guard
        llm_result = self.llm_guard.call_classification(node, node_path)
        if llm_result is not None:
            # Guard returned a validated ClassifiedSection — use it
            llm_result.is_heuristic = False
            llm_result.child_count = len(node.children)
            logger.info(
                "section_classified_llm",
                path=node_path,
                role=llm_result.section_role.value,
                confidence=llm_result.confidence,
            )
            return llm_result

        # LLM unavailable or failed — check if it's a budget/size issue
        prepared = self.llm_guard.prepare_classification_input(node)
        if prepared is None:
            result = ClassifiedSection(
                node_path=node_path,
                section_role=SectionRole.UNKNOWN,
                confidence=0.0,
                reasoning="LLM classification unavailable (budget/size limit or no client)",
                is_heuristic=False,
                child_count=len(node.children),
            )
            logger.info("section_classified_llm_unavailable", path=node_path)
            return result

        # LLM was called but failed validation — fail closed
        result = ClassifiedSection(
            node_path=node_path,
            section_role=SectionRole.UNKNOWN,
            confidence=0.0,
            reasoning="LLM classification failed (malformed response or no client configured)",
            is_heuristic=False,
            child_count=len(node.children),
        )
        logger.info("section_classified_llm_failed", path=node_path)
        return result

    def _enrich_repeat_counts(
        self, root: ComponentNode, classifications: List[ClassifiedSection]
    ) -> None:
        """
        For repeatable-shaped roles, detect structurally similar sibling
        subtrees and set repeat_instance_count.
        """
        for classified in classifications:
            if classified.section_role in REPEATABLE_ROLES:
                # Find the actual node by matching its path index
                idx = self._path_to_index(classified.node_path)
                if idx is not None and idx < len(root.children):
                    node = root.children[idx]
                    count = self._detect_repeat_pattern(node.children)
                    classified.repeat_instance_count = count

    def _detect_repeat_pattern(self, siblings: List[ComponentNode]) -> int:
        """
        Detect structurally similar sibling subtrees.

        Compares tag structure (ignoring text content). If >= 2 siblings
        share the same tag skeleton, returns the count.
        """
        if len(siblings) < 2:
            return len(siblings)

        def skeleton(node: ComponentNode, depth: int = 0, max_depth: int = 3) -> str:
            if depth >= max_depth:
                return node.tag
            child_skeletons = ",".join(
                skeleton(c, depth + 1, max_depth)
                for c in node.children
                if c.tag != "#text"
            )
            return f"{node.tag}[{child_skeletons}]" if child_skeletons else node.tag

        skeletons = [skeleton(s) for s in siblings if s.tag != "#text"]
        if not skeletons:
            return 0

        # Count the most common skeleton pattern
        from collections import Counter

        counts = Counter(skeletons)
        most_common_skeleton, most_common_count = counts.most_common(1)[0]

        if most_common_count >= 2:
            return most_common_count

        return len(skeletons)

    def _get_classes(self, node: ComponentNode) -> list[str]:
        """Extract class names from a node's attributes."""
        class_attr = node.attributes.get("class", "")
        return [c.lower() for c in class_attr.split() if c]

    def _path_to_index(self, node_path: str) -> Optional[int]:
        """Extract the child index from a node path like 'root > div:nth-child(3)'."""
        try:
            if ":nth-child(" in node_path:
                idx_str = node_path.split(":nth-child(")[1].rstrip(")")
                return int(idx_str) - 1
        except (IndexError, ValueError):
            pass
        return None
