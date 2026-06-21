from typing import List, Dict, Any
import structlog
from wire.schema.submission_schema import ContentSubstitution, TransformationPrompt
from wire.schema.canonical import ComponentNode
from wire.semantic.llm_guard import LLMGuard

logger = structlog.get_logger(__name__)

class TransformationPromptGenerator:
    """
    Generates structured and natural-language TransformationPrompts.
    """

    @staticmethod
    def generate(
        cids_root: ComponentNode,
        substitutions: List[ContentSubstitution],
        source_url: str,
        llm_guard: LLMGuard,
        design_tokens: dict = None
    ) -> TransformationPrompt:
        logger.info("generating_transformation_prompt", source_url=source_url, substitutions_count=len(substitutions))

        # Default fallback values for summaries
        design_summary = "LLM Generation Failed (graceful degradation fallback)"
        substitution_summary = "LLM Generation Failed (graceful degradation fallback)"

        # 1. Prepare design data for design summary LLM call
        design_data = {
            "source_url": source_url,
            "tokens": design_tokens or {},
            "cids_root_tag": cids_root.tag,
            "subsections": [
                {"tag": child.tag, "layout_role": child.layout_role}
                for child in cids_root.children
                if child.tag != "#text"
            ]
        }

        # 2. Call LLM for design summary via LLMGuard
        try:
            if llm_guard and llm_guard._llm_client and llm_guard._llm_client.is_available:
                summary = llm_guard.call_design_summary(design_data)
                if summary:
                    design_summary = summary
        except Exception as e:
            logger.warning("llm_design_summary_failed", error=str(e))

        # 3. Prepare substitutions data for substitution summary LLM call
        subs_data = [
            {
                "field_id": sub.field_id,
                "section_role": sub.section_role.value,
                "original_value": sub.original_value,
                "substituted_value": sub.substituted_value.value,
                "type": sub.substitution_type
            }
            for sub in substitutions
        ]

        # 4. Call LLM for substitution summary via LLMGuard
        if subs_data:
            try:
                if llm_guard and llm_guard._llm_client and llm_guard._llm_client.is_available:
                    summary = llm_guard.call_substitution_summary(subs_data)
                    if summary:
                        substitution_summary = summary
            except Exception as e:
                logger.warning("llm_substitution_summary_failed", error=str(e))
        else:
            substitution_summary = "No substitutions submitted."

        # 5. Build preserved structure notes (Phase 8 alignment)
        preserved_structure_notes = [
            "Do not modify the layout structure, tag elements, or CSS classes.",
            "Maintain the visual hierarchy and section order exactly as specified in the CIDS tree.",
            "Preserve all classes, IDs, styling rules, and element relationships.",
            "All slot bindings and dynamic bindings must remain intact.",
            "Do not mutate, remove, or reorganize structural grid or flex container boundaries."
        ]

        return TransformationPrompt(
            source_url=source_url,
            design_summary=design_summary,
            substitutions=substitutions,
            substitution_summary=substitution_summary,
            preserved_structure_notes=preserved_structure_notes
        )
