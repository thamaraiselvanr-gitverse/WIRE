"""Phase-2 content-fit / layout-safety checks for repurposing.

Slot-fill and content-presence say the user's content *landed*; they say
nothing about whether it *fits*. Real repurposing breaks when substituted
content is the wrong size for its slot: a headline three times longer than the
original blows out a hero, an off-aspect image distorts or shifts the layout, an
empty required field leaves a hole. This module inspects each substitution
against the original content and the slot's constraint and reports fit risks,
producing a 0-100 safety score the repurpose harness folds into its verdict —
so "stayed unbroken" is measured, not assumed.
"""

from typing import Dict, List, Optional

import structlog
from pydantic import BaseModel, Field

from wire.layout.section_removal_planner import SectionRemovalPlanner
from wire.schema.canonical import ComponentNode
from wire.schema.submission_schema import ContentSubstitution

logger = structlog.get_logger(__name__)


class ContentFitRisk(BaseModel):
    """A single way a substitution may not fit its slot."""

    field_id: str
    kind: str  # required_empty | text_exceeds_constraint | text_overflow | aspect_shift
    severity: str  # high | medium | low
    detail: str


class LayoutSafetyReport(BaseModel):
    """Fit risks for one repurposing pass plus a 0-100 safety score."""

    risks: List[ContentFitRisk] = Field(default_factory=list)
    safety_score: float = 100.0

    @property
    def passed(self) -> bool:
        return not self.risks


class ContentFitValidator:
    """Flags substitutions whose content is the wrong size/shape for its slot."""

    # Substituted text longer than this multiple of the original is overflow.
    OVERFLOW_RATIO = 2.5
    # Relative aspect-ratio difference beyond this distorts/shifts the slot.
    ASPECT_TOLERANCE = 0.4
    _PENALTY = {"high": 40.0, "medium": 20.0, "low": 8.0}
    _TEXT_TYPES = {"text", "url"}

    def check(
        self,
        cids_root: ComponentNode,
        substitutions: List[ContentSubstitution],
        fields_by_slot: Optional[Dict[str, object]] = None,
    ) -> LayoutSafetyReport:
        fields_by_slot = fields_by_slot or {}
        risks: List[ContentFitRisk] = []

        for sub in substitutions:
            field = fields_by_slot.get(sub.slot_id)
            required = bool(getattr(field, "required", False))
            rules = getattr(field, "validation_rules", {}) or {}
            value = sub.substituted_value.value or ""
            is_text = sub.substituted_value.type in self._TEXT_TYPES

            if required and not value.strip():
                risks.append(
                    ContentFitRisk(
                        field_id=sub.field_id,
                        kind="required_empty",
                        severity="high",
                        detail="Required slot left empty leaves a hole in the layout.",
                    )
                )
                continue

            if is_text:
                risks.extend(self._text_risks(sub, value, rules))
            else:
                aspect = self._aspect_risk(sub, cids_root)
                if aspect:
                    risks.append(aspect)

        penalty = sum(self._PENALTY.get(r.severity, 0.0) for r in risks)
        safety_score = round(max(0.0, 100.0 - penalty), 2)
        logger.info("content_fit_checked", risks=len(risks), safety_score=safety_score)
        return LayoutSafetyReport(risks=risks, safety_score=safety_score)

    def _text_risks(
        self, sub: ContentSubstitution, value: str, rules: Dict[str, object]
    ) -> List[ContentFitRisk]:
        risks: List[ContentFitRisk] = []
        max_length = rules.get("max_length")
        if isinstance(max_length, int) and len(value) > max_length:
            risks.append(
                ContentFitRisk(
                    field_id=sub.field_id,
                    kind="text_exceeds_constraint",
                    severity="medium",
                    detail=f"Text length {len(value)} exceeds slot max {max_length}.",
                )
            )
        original = (sub.original_value or "").strip()
        if len(original) >= 4 and len(value) > self.OVERFLOW_RATIO * len(original):
            risks.append(
                ContentFitRisk(
                    field_id=sub.field_id,
                    kind="text_overflow",
                    severity="medium",
                    detail=(
                        f"Text length {len(value)} is >{self.OVERFLOW_RATIO}x the "
                        f"original {len(original)}; likely to overflow its slot."
                    ),
                )
            )
        return risks

    def _aspect_risk(
        self, sub: ContentSubstitution, cids_root: ComponentNode
    ) -> Optional[ContentFitRisk]:
        new_w = sub.substituted_value.width
        new_h = sub.substituted_value.height
        if not new_w or not new_h:
            return None
        lookup = SectionRemovalPlanner.find_node_by_path(cids_root, sub.cids_node_path)
        if lookup is None:
            return None
        node, _parent, _idx = lookup
        orig_w = self._int_attr(node, "width")
        orig_h = self._int_attr(node, "height")
        if not orig_w or not orig_h:
            return None
        orig_ratio = orig_w / orig_h
        new_ratio = new_w / new_h
        if abs(new_ratio - orig_ratio) / orig_ratio > self.ASPECT_TOLERANCE:
            return ContentFitRisk(
                field_id=sub.field_id,
                kind="aspect_shift",
                severity="medium",
                detail=(
                    f"Image aspect {new_ratio:.2f} differs from the slot's "
                    f"{orig_ratio:.2f}; will distort or shift the layout."
                ),
            )
        return None

    @staticmethod
    def _int_attr(node: ComponentNode, name: str) -> Optional[int]:
        raw = node.attributes.get(name, "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        return int(digits) if digits else None
