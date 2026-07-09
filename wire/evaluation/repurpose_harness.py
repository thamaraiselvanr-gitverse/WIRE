"""Phase-0 repurposing-success harness.

Reconstruction fidelity answers "does our clone look like theirs?". It does
*not* answer WIRE's actual product question: "if a user drops their own content
into this layout, does it land correctly and stay unbroken?" That was
unmeasured — the pipeline computes ``ContentSubstitution`` records and an LLM
transformation prompt, but never applies the substitutions to produce the
repurposed page, so there was no artifact to score.

This module closes that loop. It applies substitutions to the CIDS, recompiles,
and scores the result on three honest, composable signals:

* **slot fill** — did every user field find a real node to land in?
* **content presence** — did each substituted value actually appear in output?
* **structural integrity** — did the page keep its structure vs. the original?

An optional **visual** score (SSIM outside substituted regions, browser-gated)
can be supplied by a caller that has rendered both pages. The composite is the
mean of whatever signals are available, so the number never claims more than it
measured.
"""

import copy
from typing import List, Optional, Tuple

import structlog
from pydantic import BaseModel, Field

from wire.compilers.html_compiler import HTMLCompiler
from wire.evaluation.layout_safety import ContentFitRisk, ContentFitValidator
from wire.generation.substitution_mapper import SubstitutionMapper
from wire.layout.section_removal_planner import SectionRemovalPlanner
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode
from wire.schema.submission_schema import ContentSubstitution, SubmissionPayload
from wire.validation.structural import StructuralValidator

logger = structlog.get_logger(__name__)

_IMAGE_SUB_TYPES = {"image_replace"}
_MEDIA_SUB_TYPES = {"media_replace", "document_replace"}


class FieldOutcome(BaseModel):
    """Per-substitution result: where it targeted and whether it took."""

    field_id: str
    slot_id: str
    node_path: str
    applied: bool
    present_in_output: bool
    reason: str = ""


class RepurposeReport(BaseModel):
    """Honest end-to-end repurposing scorecard for one run + payload."""

    total_fields: int
    applied_fields: int
    schema_field_count: int = 0
    slot_fill_rate: float
    content_presence_rate: float
    structural_score: Optional[float] = None
    visual_score: Optional[float] = None
    layout_safety_score: Optional[float] = None
    layout_risks: List[ContentFitRisk] = Field(default_factory=list)
    success_percent: float
    fields: List[FieldOutcome] = Field(default_factory=list)


def _first_text_descendant(node: ComponentNode) -> Optional[ComponentNode]:
    """Depth-first search for the first ``#text`` node in a subtree."""
    for child in node.children:
        if child.tag == "#text":
            return child
        found = _first_text_descendant(child)
        if found is not None:
            return found
    return None


def apply_substitutions(
    root: ComponentNode, substitutions: List[ContentSubstitution]
) -> Tuple[ComponentNode, List[FieldOutcome]]:
    """Apply substitutions to a deep copy of the CIDS, returning it + outcomes.

    Text/url substitutions replace the target node's first text descendant (or
    the node's own text); image/media substitutions set the target's ``src``
    (and ``alt`` when known). Targets are resolved by the same ``root >
    tag:nth-child(N)`` path the form schema stores, via ``find_node_by_path``.
    """
    mutated = copy.deepcopy(root)
    outcomes: List[FieldOutcome] = []

    for sub in substitutions:
        lookup = SectionRemovalPlanner.find_node_by_path(mutated, sub.cids_node_path)
        value = sub.substituted_value.value or (
            sub.substituted_value.extracted_text or ""
        )
        if lookup is None:
            outcomes.append(
                FieldOutcome(
                    field_id=sub.field_id,
                    slot_id=sub.slot_id,
                    node_path=sub.cids_node_path,
                    applied=False,
                    present_in_output=False,
                    reason="path_not_found",
                )
            )
            continue

        node, _parent, _idx = lookup
        if sub.substitution_type in _IMAGE_SUB_TYPES | _MEDIA_SUB_TYPES:
            node.attributes["src"] = value
            if sub.substituted_value.alt_text:
                node.attributes["alt"] = sub.substituted_value.alt_text
            reason = "src_set"
        else:
            target = _first_text_descendant(node) or node
            target.text_content = value
            reason = "text_set"

        outcomes.append(
            FieldOutcome(
                field_id=sub.field_id,
                slot_id=sub.slot_id,
                node_path=sub.cids_node_path,
                applied=True,
                present_in_output=False,  # filled in after recompile
                reason=reason,
            )
        )

    return mutated, outcomes


class RepurposeEvaluator:
    """Applies a content payload to a run's CIDS and scores the repurposing."""

    def evaluate(
        self,
        cids: CanonicalDesignSchema,
        form_schema: object,
        payload: SubmissionPayload,
        original_html: Optional[str] = None,
        visual_score: Optional[float] = None,
    ) -> Tuple[RepurposeReport, str]:
        """Return ``(report, substituted_html)`` for one payload against a run.

        ``original_html`` (the run's ``output_editable.html``) enables the
        structural-integrity signal. ``visual_score`` — if a caller rendered the
        pages and computed masked SSIM — is folded into the composite.
        """
        substitutions = SubstitutionMapper.map(cids.root, payload, form_schema)
        mutated_root, outcomes = apply_substitutions(cids.root, substitutions)

        substituted_html = HTMLCompiler().compile_document(
            CanonicalDesignSchema(
                url=cids.url,
                tokens=cids.tokens,
                root=mutated_root,
                global_styles=cids.global_styles,
            )
        )

        # Content presence: did each applied value actually reach the output?
        text_applied = 0
        text_present = 0
        for sub, outcome in zip(substitutions, outcomes):
            if not outcome.applied:
                continue
            value = sub.substituted_value.value or ""
            is_media = sub.substitution_type in _IMAGE_SUB_TYPES | _MEDIA_SUB_TYPES
            outcome.present_in_output = bool(value) and value in substituted_html
            if not is_media:
                text_applied += 1
                if outcome.present_in_output:
                    text_present += 1

        # Slot fill: of the user's requested top-level fields, how many landed?
        # (A repeatable group counts once; landing any instance counts.)
        requested_keys = set(payload.field_values)
        landed_keys = {
            self._requesting_key(o.field_id) for o in outcomes if o.applied
        } & requested_keys
        total = len(requested_keys)
        applied_fields = sum(1 for o in outcomes if o.applied)
        slot_fill_rate = (len(landed_keys) / total) if total else 0.0
        presence_rate = (text_present / text_applied) if text_applied else 0.0

        structural_score: Optional[float] = None
        if original_html is not None:
            structural_score = (
                StructuralValidator()
                .compare(original_html, substituted_html)
                .get("structural_score")
            )

        # How many editable slots the pipeline exposed at all — the product's
        # repurposing *capability*, independent of this payload.
        schema_field_count = len(getattr(form_schema, "fields", [])) + len(
            getattr(form_schema, "repeatable_groups", [])
        )

        # Layout safety: does the submitted content actually FIT its slot, or
        # does it overflow / distort / leave a hole? (Phase-2 content-fit check.)
        fields_by_slot: dict[str, object] = {}
        for f in getattr(form_schema, "fields", []):
            fields_by_slot[f.slot_id] = f
        for group in getattr(form_schema, "repeatable_groups", []):
            for f in getattr(group, "template_fields", []):
                fields_by_slot[f.slot_id] = f
        safety = ContentFitValidator().check(cids.root, substitutions, fields_by_slot)

        # Honesty guard: if nothing was actually repurposed (no user fields, or
        # none landed in a slot), success is 0 — a structurally-intact page that
        # accepted none of the user's content has not been repurposed. Only when
        # real substitutions applied do the quality signals compose a score.
        if applied_fields == 0:
            success = 0.0
        else:
            # presence over text subs; if all applied subs were media, presence
            # is not penalized (there was no text to verify).
            eff_presence = presence_rate if text_applied else 1.0
            components = [
                slot_fill_rate * 100.0,
                eff_presence * 100.0,
                safety.safety_score,
            ]
            if structural_score is not None:
                components.append(structural_score)
            if visual_score is not None:
                components.append(visual_score)
            success = round(sum(components) / len(components), 2)

        report = RepurposeReport(
            total_fields=total,
            applied_fields=applied_fields,
            schema_field_count=schema_field_count,
            slot_fill_rate=round(slot_fill_rate, 4),
            content_presence_rate=round(presence_rate, 4),
            structural_score=structural_score,
            visual_score=visual_score,
            layout_safety_score=safety.safety_score,
            layout_risks=safety.risks,
            success_percent=success,
            fields=outcomes,
        )
        logger.info(
            "repurpose_evaluated",
            success_percent=success,
            schema_fields=schema_field_count,
            applied=applied_fields,
            slot_fill=report.slot_fill_rate,
            presence=report.content_presence_rate,
            structural=structural_score,
            layout_safety=safety.safety_score,
        )
        return report, substituted_html

    @staticmethod
    def _requesting_key(field_id: str) -> str:
        """The top-level payload key a substitution came from (repeatable
        instances look like ``group[0].field`` → ``group``)."""
        return field_id.split("[", 1)[0]
