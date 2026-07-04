"""Coverage for the section-removal planner statics and the structural
integrity validator's five invariants — pure, no browser."""

import pytest

from wire.layout.section_removal_planner import SectionRemovalPlanner
from wire.layout.structural_integrity_validator import StructuralIntegrityValidator
from wire.schema.canonical import ComponentNode
from wire.schema.layout_schema import LayoutContainerType

P = SectionRemovalPlanner


def _n(tag, attrs=None, styles=None, children=None, **kw):
    return ComponentNode(
        tag=tag,
        attributes=attrs or {},
        styles=styles or {},
        children=children or [],
        **kw,
    )


# ── find_node_by_path ──
def test_find_node_by_path_variants():
    root = _n("root", children=[_n("nav"), _n("section", {"id": "a"})])
    assert P.find_node_by_path(root, "does-not-start-with-root") is None
    assert P.find_node_by_path(root, "root > bad$$part") is None
    assert P.find_node_by_path(root, "root > section:nth-child(9)") is None  # OOB
    assert P.find_node_by_path(root, "root > div:nth-child(1)") is None  # tag mismatch
    # Fallback (no nth-child): first matching tag.
    node, parent, idx = P.find_node_by_path(root, "root > section")
    assert node.attributes["id"] == "a" and idx == 1
    assert P.find_node_by_path(root, "root > footer") is None  # no match


def test_get_container_type():
    assert (
        P.get_container_type(_n("div", styles={"display": "grid"}))
        is LayoutContainerType.GRID
    )
    assert (
        P.get_container_type(
            _n("div", styles={"display": "flex", "flex-direction": "column"})
        )
        is LayoutContainerType.FLEX_COLUMN
    )
    assert (
        P.get_container_type(_n("div", styles={"display": "flex"}))
        is LayoutContainerType.FLEX_ROW
    )
    assert P.get_container_type(_n("div")) is LayoutContainerType.STACK


def test_grid_columns_and_closest_factor():
    assert P._parse_grid_columns("") == 1
    assert P._parse_grid_columns("repeat(3, 1fr)") == 3
    assert P._parse_grid_columns("1fr 1fr 1fr 1fr") == 4
    assert P._find_closest_factor(1, 3) == 1
    assert P._find_closest_factor(12, 3) == 3  # 3 divides 12
    assert P._find_closest_factor(10, 3) == 2  # factors of 10 near 3


def test_find_dependent_nav_links_and_shadow():
    host = _n("div", children=[_n("a", {"href": "#hero"})])
    host.shadow_root = _n("#shadow-root", children=[_n("a", {"href": "#hero"})])
    links = P.find_dependent_nav_links(host, "hero")
    assert len(links) == 2  # light-DOM anchor + shadow anchor


def test_plan_safety_rails():
    root = _n("root", children=[_n("section", {"id": "x"})])
    with pytest.raises(ValueError):
        P().plan(root, "root > div:nth-child(1) > #shadow-root > a")  # shadow target
    with pytest.raises(ValueError):
        P().plan(root, "root > section:nth-child(5)")  # not found
    with pytest.raises(ValueError):
        P().plan(root, "root")  # cannot remove root


def test_plan_non_removable():
    section = _n("section", {"id": "x"})
    section.removable = False
    root = _n("root", children=[section])
    with pytest.raises(ValueError):
        P().plan(root, "root > section:nth-child(1)")


# ── structural integrity validator ──
def test_validator_flags_orphaned_nav_and_empty_grid():
    # nav anchor points to #gone (removed), and an empty grid remains.
    mutated = _n(
        "root",
        children=[
            _n("nav", children=[_n("a", {"href": "#gone"})]),
            _n(
                "div",
                styles={"display": "grid", "grid-template-columns": "repeat(3,1fr)"},
            ),
        ],
    )
    original = _n(
        "root",
        children=[
            _n("nav", children=[_n("a", {"href": "#gone"})]),
            _n("section", {"id": "gone"}),
        ],
    )
    report = StructuralIntegrityValidator().validate(
        original, mutated, "root > section:nth-child(2)"
    )
    rules = {v.rule for v in report.violations}
    assert "no_orphaned_nav_entries" in rules
    assert "no_empty_grid_cells" in rules
    assert report.passed is False


def test_validator_passes_clean_removal():
    original = _n(
        "root",
        children=[_n("section", {"id": "a"}), _n("section", {"id": "b"})],
    )
    mutated = _n("root", children=[_n("section", {"id": "b"})])
    report = StructuralIntegrityValidator().validate(
        original, mutated, "root > section:nth-child(1)"
    )
    assert report.passed is True
    assert report.violations == []


def test_validator_missing_section_raises():
    tree = _n("root", children=[_n("section", {"id": "a"})])
    with pytest.raises(ValueError):
        StructuralIntegrityValidator().validate(
            tree, tree, "root > section:nth-child(9)"
        )
