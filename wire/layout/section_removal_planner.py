import re
from typing import List, Optional, Tuple

import structlog

from wire.schema.canonical import ComponentNode
from wire.schema.layout_schema import (
    LayoutContainerType,
    ReflowAction,
    RemovalPlan,
)

logger = structlog.get_logger(__name__)


class SectionRemovalPlanner:
    """
    Plans the removal of a section from the CIDS tree.
    Generates a RemovalPlan with ReflowActions to adjust layout, spacing, and nav.
    """

    @staticmethod
    def find_node_by_path(
        root: ComponentNode, path: str
    ) -> Optional[Tuple[ComponentNode, Optional[ComponentNode], int]]:
        """
        Finds a node and its parent + child index by its CIDS path.
        Returns (node, parent, index) or None.
        """
        parts = [p.strip() for p in path.split(">")]
        if not parts or parts[0] != "root":
            return None

        current = root
        parent = None
        index = -1

        for part in parts[1:]:
            # Parse tag:nth-child(index)
            match = re.match(r"^([\w#-]+)(?::nth-child\((\d+)\))?$", part)
            if not match:
                return None
            tag, idx_str = match.groups()
            if idx_str:
                idx = int(idx_str) - 1  # Convert to 0-indexed
                if idx < 0 or idx >= len(current.children):
                    return None
                parent = current
                index = idx
                current = current.children[idx]
                if current.tag != tag:
                    return None
            else:
                # Fallback: find first matching child tag
                found = False
                for idx, child in enumerate(current.children):
                    if child.tag == tag:
                        parent = current
                        index = idx
                        current = child
                        found = True
                        break
                if not found:
                    return None

        return current, parent, index

    @staticmethod
    def get_container_type(parent: ComponentNode) -> LayoutContainerType:
        """Determines the LayoutContainerType of a parent node."""
        display = parent.styles.get("display", "").lower().strip()
        if "grid" in display:
            return LayoutContainerType.GRID
        elif "flex" in display:
            direction = parent.styles.get("flex-direction", "").lower().strip()
            if "column" in direction:
                return LayoutContainerType.FLEX_COLUMN
            return LayoutContainerType.FLEX_ROW
        return LayoutContainerType.STACK

    @staticmethod
    def find_dependent_nav_links(
        node: ComponentNode, section_id: str, current_path: str = "root"
    ) -> List[str]:
        """Recursively find all anchor links pointing to the section ID."""
        links = []
        href = node.attributes.get("href", "").strip()
        if node.tag == "a" and (
            href == f"#{section_id}" or href.startswith(f"#{section_id}/")
        ):
            links.append(current_path)

        for idx, child in enumerate(node.children):
            child_path = f"{current_path} > {child.tag}:nth-child({idx + 1})"
            links.extend(
                SectionRemovalPlanner.find_dependent_nav_links(
                    child, section_id, child_path
                )
            )

        if node.shadow_root:
            shadow_path = f"{current_path} > #shadow-root"
            links.extend(
                SectionRemovalPlanner.find_dependent_nav_links(
                    node.shadow_root, section_id, shadow_path
                )
            )

        return links

    @staticmethod
    def _parse_grid_columns(grid_style: str) -> int:
        """Extract number of columns from grid-template-columns string."""
        if not grid_style:
            return 1
        # Match repeat(3, 1fr)
        match = re.search(r"repeat\(\s*(\d+)\s*,", grid_style)
        if match:
            return int(match.group(1))
        # Match 1fr 1fr 1fr
        parts = [p.strip() for p in grid_style.split() if p.strip()]
        return len(parts) if parts else 1

    @staticmethod
    def _find_closest_factor(n: int, target: int) -> int:
        """Finds factor of n closest to target, preferring larger factor for ties."""
        if n <= 1:
            return 1
        factors = [i for i in range(1, n + 1) if n % i == 0]
        return min(factors, key=lambda x: (abs(x - target), -x))

    def plan(self, cids_root: ComponentNode, section_node_path: str) -> RemovalPlan:
        """Generates a RemovalPlan for the node at the specified path."""
        # Safety Rail: forbid targeting inside shadow roots
        if "#shadow-root" in section_node_path:
            raise ValueError("Cannot target nodes inside a shadow root for removal")

        lookup = self.find_node_by_path(cids_root, section_node_path)
        if not lookup:
            raise ValueError(f"Node not found at path: {section_node_path}")

        node, parent, index = lookup
        if not parent:
            raise ValueError("Cannot remove the root node")

        # Safety Rail: check removable property
        if not node.removable:
            raise ValueError(
                f"Node at path {section_node_path} is marked non-removable"
            )

        container_type = self.get_container_type(parent)

        # Identify affected siblings
        parent_path = section_node_path.rsplit(" > ", 1)[0]
        affected_siblings = []
        for idx, child in enumerate(parent.children):
            child_path = f"{parent_path} > {child.tag}:nth-child({idx + 1})"
            if child_path != section_node_path:
                affected_siblings.append(child_path)

        # Identify dependent nav entries
        section_id = node.attributes.get("id")
        affected_nav_entries = []
        if section_id:
            affected_nav_entries = self.find_dependent_nav_links(cids_root, section_id)

        reflow_actions = []

        # 1. Nav entry removal actions
        for nav_path in affected_nav_entries:
            reflow_actions.append(
                ReflowAction(
                    action_type="remove_nav_entry",
                    target_node_path=nav_path,
                )
            )

        # 2. Container-specific reflow actions
        if container_type == LayoutContainerType.GRID:
            # Design Decision: Preserve the original grid column count to maintain visual scale,
            # card dimensions, and layout rhythm (e.g. keeping 3 columns for 5 items).
            # Changing columns from 3 to 5 (or 3 to 1) alters the card size drastically,
            # which breaks visual resemblance to the original design. A partial last row is
            # standard in modern web design and is visually stable.
            pass

        elif container_type in (
            LayoutContainerType.FLEX_ROW,
            LayoutContainerType.FLEX_COLUMN,
        ):
            # Recompute flex basis for siblings if percentage widths are used
            remaining_count = len(parent.children) - 1
            if remaining_count > 0:
                for sib_path in affected_siblings:
                    _found = self.find_node_by_path(cids_root, sib_path)
                    if _found:
                        sib_node, _, _ = _found
                        # Check width or flex-basis
                        width = sib_node.styles.get("width", "")
                        flex_basis = sib_node.styles.get("flex-basis", "")

                        target_prop = None
                        orig_val = None
                        if "%" in width:
                            target_prop = "width"
                            orig_val = width
                        elif "%" in flex_basis:
                            target_prop = "flex-basis"
                            orig_val = flex_basis

                        if target_prop:
                            new_percent = f"{round(100 / remaining_count, 2)}%"
                            reflow_actions.append(
                                ReflowAction(
                                    action_type="recompute_flex_basis",
                                    target_node_path=sib_path,
                                    before_value={target_prop: orig_val},
                                    after_value={target_prop: new_percent},
                                )
                            )

        # 3. Spacing gap closing
        # For vertical containers (STACK/FLEX_COLUMN), check if adjacent siblings need margin adjustment
        if container_type in (
            LayoutContainerType.STACK,
            LayoutContainerType.FLEX_COLUMN,
        ):
            remaining_count = len(parent.children) - 1
            if remaining_count > 0:
                # Find sibling before and after
                sib_before = parent.children[index - 1] if index > 0 else None
                sib_after = (
                    parent.children[index + 1]
                    if index < len(parent.children) - 1
                    else None
                )

                if sib_before and sib_after:
                    # Sibling before path
                    sib_before_path = (
                        f"{parent_path} > {sib_before.tag}:nth-child({index})"
                    )

                    # Compute transfer margin: if sibling before has 0 margin and removed had margin,
                    # transfer the removed node's margin to keep spacing clean
                    removed_margin_bottom = node.styles.get("margin-bottom", "0px")

                    # Simple heuristic: set sibling before margin-bottom to removed margin-bottom
                    if (
                        removed_margin_bottom != "0px"
                        and sib_before.styles.get("margin-bottom", "0px") == "0px"
                    ):
                        reflow_actions.append(
                            ReflowAction(
                                action_type="close_spacing_gap",
                                target_node_path=sib_before_path,
                                before_value={"margin-bottom": "0px"},
                                after_value={"margin-bottom": removed_margin_bottom},
                            )
                        )

        # 4. Section order renumbering
        # Renumber order or data-section-index if present on remaining siblings
        section_idx = 1
        for sib_path in affected_siblings:
            _found = self.find_node_by_path(cids_root, sib_path)
            if _found:
                sib_node, _, _ = _found
                before_vals = {}
                after_vals = {}

                has_index = "data-section-index" in sib_node.attributes
                has_order = "order" in sib_node.styles

                if has_index or has_order:
                    if has_index:
                        before_vals["data-section-index"] = sib_node.attributes[
                            "data-section-index"
                        ]
                        after_vals["data-section-index"] = str(section_idx)
                    if has_order:
                        before_vals["order"] = sib_node.styles["order"]
                        after_vals["order"] = str(section_idx)

                    reflow_actions.append(
                        ReflowAction(
                            action_type="renumber_order",
                            target_node_path=sib_path,
                            before_value=before_vals,
                            after_value=after_vals,
                        )
                    )
                    section_idx += 1

        # Sort actions to be predictable: remove nav entries first, then resize/recompute, then renumber
        action_order = {
            "remove_nav_entry": 0,
            "resize_grid": 1,
            "recompute_flex_basis": 1,
            "close_spacing_gap": 2,
            "renumber_order": 3,
        }
        reflow_actions.sort(key=lambda a: action_order.get(a.action_type, 4))

        plan = RemovalPlan(
            section_node_path=section_node_path,
            affected_siblings=affected_siblings,
            affected_nav_entries=affected_nav_entries,
            container_type=container_type,
            reflow_actions=reflow_actions,
        )

        logger.info(
            "section_removal_plan_generated",
            path=section_node_path,
            container=container_type.value,
            actions=len(reflow_actions),
        )
        return plan
