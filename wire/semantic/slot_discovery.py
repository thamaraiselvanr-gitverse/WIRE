"""Heuristic slot discovery — the no-LLM floor for repurposable content.

The form-schema compiler only emits a fillable field for a CIDS node that
already carries a ``slot_id`` bound in the ``InputBlueprint``. Nothing populated
those: the parser never set ``slot_id`` and the pipeline passed a one-slot stub
blueprint, so a reconstructed page exposed **zero** editable slots — there was
nothing to repurpose without an LLM.

This discoverer walks the CIDS, assigns a ``slot_id`` to each node that holds
real, user-replaceable content (leaf text, images), and returns a populated
``InputBlueprint``. It mutates the tree in place so the same slot bindings flow
to the saved CIDS, the form schema, and content substitution. An LLM, when
available, refines/renames these slots — but the product now works without one.
"""

from typing import List, Optional

import structlog

from wire.schema.canonical import ComponentNode
from wire.schema.input_blueprint import DataSlot, InputBlueprint, SlotConstraint

logger = structlog.get_logger(__name__)


class HeuristicSlotDiscoverer:
    """Assigns slot_ids to replaceable content nodes and builds a blueprint."""

    # Inline/heading/label tags whose direct text a user would replace.
    TEXT_TAGS = {
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "span", "a", "button", "li", "blockquote", "figcaption",
        "label", "strong", "em", "small", "td", "th", "dt", "dd",
        "summary", "cite", "q", "b", "i", "caption",
    }  # fmt: skip
    IMAGE_TAGS = {"img"}

    # Guard against pathological pages minting thousands of slots.
    MAX_SLOTS = 300
    # Text longer than this becomes a TEXTAREA downstream; the constraint's
    # max_length drives that, so size the allowance generously off the original.
    _MIN_TEXT_ALLOWANCE = 80

    def discover(self, root: ComponentNode) -> InputBlueprint:
        """Mutate ``root`` (assign slot_ids) and return the populated blueprint."""
        blueprint = InputBlueprint()
        counter = [0]

        def assign(node: ComponentNode, slot: DataSlot) -> None:
            node.slot_id = slot.id
            blueprint.slots[slot.id] = slot

        def visit(node: ComponentNode) -> None:
            if len(blueprint.slots) >= self.MAX_SLOTS:
                return
            if node.tag not in ("#text", "#shadow-root") and not node.slot_id:
                if node.tag in self.IMAGE_TAGS and node.attributes.get("src"):
                    counter[0] += 1
                    assign(
                        node,
                        DataSlot(
                            id=f"slot_{node.tag}_{counter[0]}",
                            type="image",
                            constraint=SlotConstraint(allowed_types=["image"]),
                        ),
                    )
                elif node.tag in self.TEXT_TAGS:
                    text = self._direct_text(node)
                    if text is not None:
                        counter[0] += 1
                        assign(
                            node,
                            DataSlot(
                                id=f"slot_{node.tag}_{counter[0]}",
                                type="text",
                                constraint=SlotConstraint(
                                    allowed_types=["text"],
                                    max_length=max(
                                        self._MIN_TEXT_ALLOWANCE, len(text) * 2
                                    ),
                                ),
                            ),
                        )
            for child in node.children:
                visit(child)
            if node.shadow_root:
                visit(node.shadow_root)

        visit(root)
        logger.info("slots_discovered", count=len(blueprint.slots))
        return blueprint

    @staticmethod
    def _direct_text(node: ComponentNode) -> Optional[str]:
        """The node's own replaceable text: a direct ``#text`` child with at
        least two characters and some alphanumeric content (skips bullets,
        separators, and whitespace-only nodes)."""
        for child in node.children:
            if child.tag == "#text" and child.text_content:
                stripped = child.text_content.strip()
                if len(stripped) >= 2 and any(ch.isalnum() for ch in stripped):
                    return stripped
        return None

    @staticmethod
    def slot_ids(root: ComponentNode) -> List[str]:
        """All slot_ids currently bound in a tree (diagnostic/testing helper)."""
        found: List[str] = []

        def walk(node: ComponentNode) -> None:
            if node.slot_id:
                found.append(node.slot_id)
            for child in node.children:
                walk(child)
            if node.shadow_root:
                walk(node.shadow_root)

        walk(root)
        return found
