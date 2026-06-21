import structlog
from typing import Dict, Any

from wire.schema.canonical import ComponentNode
from wire.schema.layout_schema import RemovalPlan, ReflowAction
from wire.layout.section_removal_planner import SectionRemovalPlanner

logger = structlog.get_logger(__name__)

class LayoutReflowEngine:
    """
    Executes a RemovalPlan on a CIDS tree.
    Returns a new mutated tree without in-place modification of the original.
    """

    @staticmethod
    def execute(cids_root: ComponentNode, plan: RemovalPlan) -> ComponentNode:
        """
        Applies the removal plan to a deep copy of the tree and returns the new tree.
        """
        # Create a deep copy of the original tree
        mutated_root = cids_root.model_copy(deep=True)

        # Resolve the section node and its parent in the new tree first
        section_lookup = SectionRemovalPlanner.find_node_by_path(mutated_root, plan.section_node_path)
        if not section_lookup:
            raise ValueError(f"Section node not found in mutated tree: {plan.section_node_path}")
        
        section_node, section_parent, _ = section_lookup

        # Resolve all action targets in the new tree
        resolved_actions = []
        for action in plan.reflow_actions:
            target_lookup = SectionRemovalPlanner.find_node_by_path(mutated_root, action.target_node_path)
            if target_lookup:
                target_node, target_parent, target_idx = target_lookup
                resolved_actions.append((action, target_node, target_parent, target_idx))
            else:
                logger.warning("reflow_target_not_resolved", path=action.target_node_path)

        # Apply actions
        nodes_to_remove = []

        for action, target_node, target_parent, target_idx in resolved_actions:
            if action.action_type == "remove_nav_entry":
                # Mark nav entry for removal
                if target_parent:
                    nodes_to_remove.append((target_parent, target_node))
            
            elif action.action_type == "resize_grid":
                # Update grid columns
                for prop, val in action.after_value.items():
                    target_node.styles[prop] = val
                    logger.info("reflow_grid_resized", path=action.target_node_path, prop=prop, val=val)

            elif action.action_type == "recompute_flex_basis":
                # Update flex basis / width
                for prop, val in action.after_value.items():
                    target_node.styles[prop] = val
                    logger.info("reflow_flex_recomputed", path=action.target_node_path, prop=prop, val=val)

            elif action.action_type == "close_spacing_gap":
                # Update spacing margins
                for prop, val in action.after_value.items():
                    target_node.styles[prop] = val
                    logger.info("reflow_spacing_adjusted", path=action.target_node_path, prop=prop, val=val)

            elif action.action_type == "renumber_order":
                # Update attributes or styles for contiguous ordering
                for prop, val in action.after_value.items():
                    if prop in target_node.attributes:
                        target_node.attributes[prop] = val
                    elif prop in target_node.styles:
                        target_node.styles[prop] = val
                    logger.info("reflow_order_renumbered", path=action.target_node_path, prop=prop, val=val)

        # 1. Perform structural removals of nav entries
        for parent_node, child_node in nodes_to_remove:
            parent_node.children = [c for c in parent_node.children if c is not child_node]
            logger.info("reflow_nav_entry_removed", tag=child_node.tag)

        # 2. Perform structural removal of the section itself
        if section_parent:
            section_parent.children = [c for c in section_parent.children if c is not section_node]
            logger.info("reflow_section_removed", path=plan.section_node_path)

        return mutated_root
