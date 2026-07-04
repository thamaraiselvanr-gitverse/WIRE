from typing import Any, Dict, List

import structlog

from wire.schema.canonical import ComponentNode
from wire.schema.submission_schema import ContentSubstitution, TransformationPrompt
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
        design_tokens: dict = None,
    ) -> TransformationPrompt:
        logger.info(
            "generating_transformation_prompt",
            source_url=source_url,
            substitutions_count=len(substitutions),
        )

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
            ],
        }

        # 2. Call LLM for design summary via LLMGuard
        try:
            if (
                llm_guard
                and llm_guard._llm_client
                and llm_guard._llm_client.is_available
            ):
                summary = llm_guard.call_design_summary(design_data)
                if summary:
                    design_summary = summary
        except Exception as e:
            logger.warning("llm_design_summary_failed", error=str(e))

        # 3. Prepare substitutions data for substitution summary LLM call
        subs_data = TransformationPromptGenerator._build_subs_data(substitutions)

        # 4. Call LLM for substitution summary via LLMGuard
        if subs_data:
            try:
                if (
                    llm_guard
                    and llm_guard._llm_client
                    and llm_guard._llm_client.is_available
                ):
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
            "Do not mutate, remove, or reorganize structural grid or flex container boundaries.",
        ]

        return TransformationPrompt(
            source_url=source_url,
            design_summary=design_summary,
            substitutions=substitutions,
            substitution_summary=substitution_summary,
            preserved_structure_notes=preserved_structure_notes,
        )

    # Cap document text sent to the LLM so a large upload can't blow the prompt.
    _MAX_DOC_TEXT_CHARS = 4000

    @staticmethod
    def _build_subs_data(
        substitutions: List[ContentSubstitution],
    ) -> List[Dict[str, Any]]:
        """Serialize substitutions for the LLM summary.

        For media/document substitutions the stored file path is not useful to
        the model; where a document carried extracted text, that text is the
        effective substituted content, so it is surfaced (truncated) instead of
        the path — enabling content-aware substitution summaries.
        """
        subs_data: List[Dict[str, Any]] = []
        for sub in substitutions:
            ref = sub.substituted_value
            entry: Dict[str, Any] = {
                "field_id": sub.field_id,
                "section_role": sub.section_role.value,
                "original_value": sub.original_value,
                "substituted_value": ref.value,
                "type": sub.substitution_type,
                "value_kind": ref.type,
            }
            if ref.extracted_text:
                entry["document_text"] = ref.extracted_text[
                    : TransformationPromptGenerator._MAX_DOC_TEXT_CHARS
                ]
            # Image understanding: accessible alt + palette hint for the slot.
            if getattr(ref, "alt_text", None):
                entry["alt_text"] = ref.alt_text
            if getattr(ref, "dominant_color", None):
                entry["dominant_color"] = ref.dominant_color
            # Document structure: title/summary/headings for precise placement.
            if getattr(ref, "structure", None):
                struct = ref.structure or {}
                entry["document_structure"] = {
                    "title": struct.get("title"),
                    "summary": struct.get("summary"),
                    "headings": (struct.get("headings") or [])[:10],
                }
            subs_data.append(entry)
        return subs_data
