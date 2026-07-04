from enum import Enum
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from wire.schema.canonical import ComponentNode


class LayoutContainerType(str, Enum):
    GRID = "grid"
    FLEX_ROW = "flex_row"
    FLEX_COLUMN = "flex_column"
    STACK = "stack"
    ABSOLUTE_POSITIONED = "absolute_positioned"
    UNKNOWN = "unknown"


class ReflowAction(BaseModel):
    action_type: Literal[
        "resize_grid",
        "recompute_flex_basis",
        "remove_nav_entry",
        "close_spacing_gap",
        "renumber_order",
    ]
    target_node_path: str
    before_value: Dict[str, Any] = Field(default_factory=dict)
    after_value: Dict[str, Any] = Field(default_factory=dict)


class RemovalPlan(BaseModel):
    section_node_path: str
    affected_siblings: List[str] = Field(default_factory=list)
    affected_nav_entries: List[str] = Field(default_factory=list)
    container_type: LayoutContainerType
    reflow_actions: List[ReflowAction] = Field(default_factory=list)


class IntegrityViolation(BaseModel):
    node_path: str
    rule: str
    detail: str


class IntegrityReport(BaseModel):
    passed: bool
    violations: List[IntegrityViolation] = Field(default_factory=list)


class RemovalResult(BaseModel):
    mutated_root: ComponentNode
    plans: List[RemovalPlan] = Field(default_factory=list)
    integrity_report: IntegrityReport
    recompilation_triggered: bool
