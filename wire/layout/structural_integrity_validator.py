from typing import List, Tuple, Set
import structlog

from wire.schema.canonical import ComponentNode
from wire.schema.layout_schema import IntegrityReport, IntegrityViolation
from wire.layout.section_removal_planner import SectionRemovalPlanner

logger = structlog.get_logger(__name__)

class StructuralIntegrityValidator:
    """
    Validates structural invariants between original and mutated trees
    after a section removal.
    """

    @staticmethod
    def _collect_ids(node: ComponentNode) -> Set[str]:
        """Collects all element IDs in a tree."""
        ids = set()
        node_id = node.attributes.get("id")
        if node_id:
            ids.add(node_id.strip())
        
        for child in node.children:
            ids.update(StructuralIntegrityValidator._collect_ids(child))
        
        if node.shadow_root:
            ids.update(StructuralIntegrityValidator._collect_ids(node.shadow_root))
        return ids

    @staticmethod
    def _collect_slot_ids(node: ComponentNode) -> Set[str]:
        """Collects all slot IDs in a tree/subtree."""
        slots = set()
        if node.slot_id:
            slots.add(node.slot_id)
        for child in node.children:
            slots.update(StructuralIntegrityValidator._collect_slot_ids(child))
        if node.shadow_root:
            slots.update(StructuralIntegrityValidator._collect_slot_ids(node.shadow_root))
        return slots

    @staticmethod
    def _collect_spacing_scale(node: ComponentNode) -> Set[str]:
        """Collects all unique spacing property values (margins/paddings) to define the page scale."""
        scale = set()
        spacing_props = {
            "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
            "padding", "padding-top", "padding-bottom", "padding-left", "padding-right"
        }
        for prop in spacing_props:
            val = node.styles.get(prop)
            if val:
                val_clean = val.strip().lower()
                if val_clean not in ("0", "0px", "auto", "none", ""):
                    scale.add(val_clean)
        
        for child in node.children:
            scale.update(StructuralIntegrityValidator._collect_spacing_scale(child))
        
        if node.shadow_root:
            scale.update(StructuralIntegrityValidator._collect_spacing_scale(node.shadow_root))
        return scale

    @staticmethod
    def _check_orphaned_nav(node: ComponentNode, all_ids: Set[str], path: str = "root") -> List[IntegrityViolation]:
        """Recursively checks for orphaned anchor links."""
        violations = []
        href = node.attributes.get("href", "").strip()
        if node.tag == "a" and href.startswith("#") and len(href) > 1:
            target_id = href[1:].split("/")[0]  # strip any subpath
            if target_id not in all_ids:
                violations.append(IntegrityViolation(
                    node_path=path,
                    rule="no_orphaned_nav_entries",
                    detail=f"Anchor points to missing ID: {target_id}",
                ))

        for idx, child in enumerate(node.children):
            child_path = f"{path} > {child.tag}:nth-child({idx + 1})"
            violations.extend(StructuralIntegrityValidator._check_orphaned_nav(child, all_ids, child_path))

        if node.shadow_root:
            violations.extend(StructuralIntegrityValidator._check_orphaned_nav(node.shadow_root, all_ids, f"{path} > #shadow-root"))
        return violations

    @staticmethod
    def _check_grid_capacity(node: ComponentNode, path: str = "root") -> List[IntegrityViolation]:
        """Recursively checks grid layout sanity (non-empty items and valid columns). Partial last rows are accepted."""
        violations = []
        display = node.styles.get("display", "").lower()
        if "grid" in display:
            cols_style = node.styles.get("grid-template-columns", "")
            cols = SectionRemovalPlanner._parse_grid_columns(cols_style)
            n_items = len(node.children)
            if n_items == 0:
                violations.append(IntegrityViolation(
                    node_path=path,
                    rule="no_empty_grid_cells",
                    detail="Grid has 0 items, leaving all cells empty.",
                ))
            elif cols <= 0:
                violations.append(IntegrityViolation(
                    node_path=path,
                    rule="no_empty_grid_cells",
                    detail=f"Grid has invalid column count: {cols}",
                ))

        for idx, child in enumerate(node.children):
            child_path = f"{path} > {child.tag}:nth-child({idx + 1})"
            violations.extend(StructuralIntegrityValidator._check_grid_capacity(child, child_path))

        if node.shadow_root:
            violations.extend(StructuralIntegrityValidator._check_grid_capacity(node.shadow_root, f"{path} > #shadow-root"))
        return violations

    @staticmethod
    def _check_section_ordering(node: ComponentNode, path: str = "root") -> List[IntegrityViolation]:
        """Recursively checks that ordering attributes (data-section-index / order) remain contiguous."""
        violations = []
        indices = []
        orders = []

        for child in node.children:
            idx_val = child.attributes.get("data-section-index")
            if idx_val:
                try:
                    indices.append(int(idx_val))
                except ValueError:
                    pass
            order_val = child.styles.get("order")
            if order_val:
                try:
                    orders.append(int(order_val))
                except ValueError:
                    pass

        if indices:
            indices.sort()
            expected = list(range(1, len(indices) + 1))
            if indices != expected:
                violations.append(IntegrityViolation(
                    node_path=path,
                    rule="contiguous_section_ordering",
                    detail=f"data-section-index values are not contiguous: {indices} (expected {expected})",
                ))

        if orders:
            orders.sort()
            expected = list(range(1, len(orders) + 1))
            if orders != expected:
                violations.append(IntegrityViolation(
                    node_path=path,
                    rule="contiguous_section_ordering",
                    detail=f"CSS flex/grid orders are not contiguous: {orders} (expected {expected})",
                ))

        for idx, child in enumerate(node.children):
            child_path = f"{path} > {child.tag}:nth-child({idx + 1})"
            violations.extend(StructuralIntegrityValidator._check_section_ordering(child, child_path))

        if node.shadow_root:
            violations.extend(StructuralIntegrityValidator._check_section_ordering(node.shadow_root, f"{path} > #shadow-root"))
        return violations

    @staticmethod
    def _check_spacing_scales(node: ComponentNode, allowed_scale: Set[str], path: str = "root") -> List[IntegrityViolation]:
        """Recursively checks that spacing values remain in the page's scale."""
        violations = []
        spacing_props = {
            "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
            "padding", "padding-top", "padding-bottom", "padding-left", "padding-right"
        }
        for prop in spacing_props:
            val = node.styles.get(prop)
            if val:
                val_clean = val.strip().lower()
                if val_clean in ("0", "0px", "auto", "none", ""):
                    continue
                if val_clean not in allowed_scale:
                    violations.append(IntegrityViolation(
                        node_path=path,
                        rule="spacing_scale_invariance",
                        detail=f"Spacing property '{prop}: {val}' falls outside the page scale.",
                    ))

        for idx, child in enumerate(node.children):
            child_path = f"{path} > {child.tag}:nth-child({idx + 1})"
            violations.extend(StructuralIntegrityValidator._check_spacing_scales(child, allowed_scale, child_path))

        if node.shadow_root:
            violations.extend(StructuralIntegrityValidator._check_spacing_scales(node.shadow_root, allowed_scale, f"{path} > #shadow-root"))
        return violations

    @staticmethod
    def _check_dangling_slots(node: ComponentNode, removed_slots: Set[str], path: str = "root") -> List[IntegrityViolation]:
        """Recursively checks that no removed slot_ids remain in the tree."""
        violations = []
        if node.slot_id and node.slot_id in removed_slots:
            violations.append(IntegrityViolation(
                node_path=path,
                rule="no_dangling_slot_references",
                detail=f"Dangling slot_id reference '{node.slot_id}' remains in tree.",
            ))

        for idx, child in enumerate(node.children):
            child_path = f"{path} > {child.tag}:nth-child({idx + 1})"
            violations.extend(StructuralIntegrityValidator._check_dangling_slots(child, removed_slots, child_path))

        if node.shadow_root:
            violations.extend(StructuralIntegrityValidator._check_dangling_slots(node.shadow_root, removed_slots, f"{path} > #shadow-root"))
        return violations

    def validate(self, original_tree: ComponentNode, mutated_tree: ComponentNode, section_node_path: str) -> IntegrityReport:
        """
        Validates five invariants:
        1. No orphaned nav links
        2. No empty grid cells
        3. Contiguous section ordering
        4. Spacing within existing scale
        5. No dangling slot_ids
        """
        violations = []

        # Find the node being removed in the original tree
        lookup = SectionRemovalPlanner.find_node_by_path(original_tree, section_node_path)
        if not lookup:
            raise ValueError(f"Section node not found in original tree: {section_node_path}")
        section_node, _, _ = lookup

        # 1. No orphaned nav links
        all_mutated_ids = self._collect_ids(mutated_tree)
        violations.extend(self._check_orphaned_nav(mutated_tree, all_mutated_ids))

        # 2. No empty grid cells
        violations.extend(self._check_grid_capacity(mutated_tree))

        # 3. Contiguous section ordering
        violations.extend(self._check_section_ordering(mutated_tree))

        # 4. Spacing scales (must fit page scale from original tree)
        original_scale = self._collect_spacing_scale(original_tree)
        violations.extend(self._check_spacing_scales(mutated_tree, original_scale))

        # 5. No dangling slot references
        removed_slots = self._collect_slot_ids(section_node)
        violations.extend(self._check_dangling_slots(mutated_tree, removed_slots))

        passed = len(violations) == 0
        report = IntegrityReport(passed=passed, violations=violations)

        logger.info(
            "structural_integrity_validation_complete",
            passed=passed,
            violations=len(violations),
        )
        return report
