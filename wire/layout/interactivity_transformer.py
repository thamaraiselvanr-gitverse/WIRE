"""Phase-3 declarative interactivity — restore JS-driven components CSS-only.

The editable compiler drops all JavaScript, so components that depended on it —
dropdown menus, accordions/disclosures, tabs — render dead: a dropdown's submenu
sits open or vanished, an accordion shows every panel at once. Rather than
re-run untrusted page JS, this transformer detects common interaction patterns
and re-expresses them with safe, declarative HTML/CSS that browsers animate
natively:

* **Dropdown / submenu** → hidden by default, revealed on ``:hover`` /
  ``:focus-within`` via an injected scoped rule (no DOM surgery).
* **ARIA disclosure** (``aria-expanded`` + ``aria-controls``) → native
  ``<details>/<summary>``, which is zero-JS and accessible.

It runs on a copy of the CIDS to produce a separate ``output_interactive.html``
artifact, so the pixel-scored ``output_editable.html`` is never altered.
"""

import copy
from typing import Dict, List, Optional, Tuple

import structlog
from pydantic import BaseModel, Field

from wire.schema.canonical import ComponentNode

logger = structlog.get_logger(__name__)


class RestoredComponent(BaseModel):
    """One interactive component re-expressed declaratively."""

    kind: str  # "dropdown" | "disclosure"
    detail: str = ""


class InteractivityReport(BaseModel):
    """What the transformer restored, plus any CSS it needs emitted."""

    restored: List[RestoredComponent] = Field(default_factory=list)
    injected_styles: List[str] = Field(default_factory=list)


class InteractivityTransformer:
    """Re-express JS-driven components as declarative CSS/HTML on a CIDS copy."""

    _DROPDOWN_CLASS_HINTS = (
        "dropdown",
        "has-submenu",
        "has-children",
        "menu-item-has-children",
        "has-dropdown",
    )
    _SUBMENU_CLASS_HINTS = ("submenu", "sub-menu", "dropdown-menu", "dropdown-content")

    def transform(
        self, root: ComponentNode
    ) -> Tuple[ComponentNode, InteractivityReport]:
        """Return ``(interactive_root, report)`` — ``root`` is not mutated."""
        mutated = copy.deepcopy(root)
        report = InteractivityReport()
        self._counter = 0
        self._walk(mutated, report)
        logger.info(
            "interactivity_transformed",
            restored=len(report.restored),
            dropdowns=sum(1 for r in report.restored if r.kind == "dropdown"),
            disclosures=sum(1 for r in report.restored if r.kind == "disclosure"),
        )
        return mutated, report

    # ── traversal ──────────────────────────────────────────────────────────
    def _walk(self, node: ComponentNode, report: InteractivityReport) -> None:
        # Accordions rewrite this node's child list; do it before recursing so
        # the newly-wrapped <details> subtrees are themselves visited.
        self._restore_disclosures(node, report)
        if self._is_dropdown_parent(node):
            self._restore_dropdown(node, report)
        for child in node.children:
            self._walk(child, report)

    # ── dropdowns (CSS-only, non-destructive) ────────────────────────────────
    def _is_submenu(self, node: ComponentNode) -> bool:
        if node.tag in ("ul", "ol"):
            return True
        cls = node.attributes.get("class", "").lower()
        role = node.attributes.get("role", "").lower()
        return role == "menu" or any(h in cls for h in self._SUBMENU_CLASS_HINTS)

    def _is_dropdown_parent(self, node: ComponentNode) -> bool:
        cls = node.attributes.get("class", "").lower()
        if not any(h in cls for h in self._DROPDOWN_CLASS_HINTS):
            return False
        return any(self._is_submenu(c) for c in node.children)

    def _restore_dropdown(
        self, node: ComponentNode, report: InteractivityReport
    ) -> None:
        submenu = next((c for c in node.children if self._is_submenu(c)), None)
        if submenu is None:
            return
        self._counter += 1
        parent_cls = f"wire-dd-{self._counter}"
        menu_cls = f"wire-dd-menu-{self._counter}"
        self._add_class(node, parent_cls)
        self._add_class(submenu, menu_cls)
        report.injected_styles.append(
            f".{menu_cls}{{display:none;}}\n"
            f".{parent_cls}:hover>.{menu_cls},"
            f".{parent_cls}:focus-within>.{menu_cls}{{display:block;}}"
        )
        report.restored.append(
            RestoredComponent(kind="dropdown", detail=f".{parent_cls}")
        )

    # ── ARIA disclosure -> <details>/<summary> ───────────────────────────────
    @staticmethod
    def _is_trigger(node: ComponentNode) -> bool:
        return node.attributes.get("aria-expanded") in ("true", "false") and bool(
            node.attributes.get("aria-controls")
        )

    def _restore_disclosures(
        self, parent: ComponentNode, report: InteractivityReport
    ) -> None:
        # Map id -> index so a trigger's aria-controls target is resolvable.
        id_index: Dict[str, int] = {}
        for i, child in enumerate(parent.children):
            cid = child.attributes.get("id")
            if cid:
                id_index[cid] = i

        new_children: List[ComponentNode] = []
        consumed: set[int] = set()
        for i, child in enumerate(parent.children):
            if i in consumed:
                continue
            if self._is_trigger(child):
                target_id = child.attributes["aria-controls"]
                j = id_index.get(target_id)
                if j is not None and j != i and j not in consumed:
                    new_children.append(self._make_details(child, parent.children[j]))
                    consumed.add(j)
                    report.restored.append(
                        RestoredComponent(kind="disclosure", detail=f"#{target_id}")
                    )
                    continue
            new_children.append(child)
        # Only commit if we actually changed something (keeps identity stable).
        if len(new_children) != len(parent.children):
            parent.children = new_children

    @staticmethod
    def _make_details(trigger: ComponentNode, panel: ComponentNode) -> ComponentNode:
        summary_attrs = {
            k: v
            for k, v in trigger.attributes.items()
            if k not in ("aria-expanded", "aria-controls", "role")
        }
        summary = ComponentNode(
            tag="summary",
            attributes=summary_attrs,
            styles=dict(trigger.styles),
            text_content=trigger.text_content,
            children=list(trigger.children),
        )
        details_attrs: Dict[str, str] = {}
        if trigger.attributes.get("aria-expanded") == "true":
            details_attrs["open"] = "open"
        return ComponentNode(
            tag="details", attributes=details_attrs, children=[summary, panel]
        )

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _add_class(node: ComponentNode, cls: str) -> None:
        existing: Optional[str] = node.attributes.get("class")
        node.attributes["class"] = f"{existing} {cls}" if existing else cls
