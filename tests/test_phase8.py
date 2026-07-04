import json
import os
import tempfile

import pytest

from wire.layout.layout_reflow_engine import LayoutReflowEngine
from wire.layout.section_removal_planner import SectionRemovalPlanner
from wire.layout.structural_integrity_validator import StructuralIntegrityValidator
from wire.orchestrator.execution_router import ExecutionRouter
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode, DesignTokens
from wire.schema.layout_schema import LayoutContainerType
from wire.templates.versioning import TemplateVersioning


def _make_node(
    tag: str,
    attrs: dict = None,
    styles: dict = None,
    children: list = None,
    slot_id: str = None,
    shadow_root: ComponentNode = None,
    removable: bool = True,
    text: str = None,
) -> ComponentNode:
    return ComponentNode(
        tag=tag,
        attributes=attrs or {},
        styles=styles or {},
        children=children or [],
        slot_id=slot_id,
        shadow_root=shadow_root,
        removable=removable,
        text_content=text,
    )


class TestRemovalPlanning:
    def test_basic_removal_plan(self):
        # A simple tree with a navigation section and 3 other sections
        root = _make_node(
            "div",
            styles={"display": "block"},
            children=[
                _make_node(
                    "nav",
                    {"id": "main-nav"},
                    children=[
                        _make_node("a", {"href": "#hero"}),
                        _make_node("a", {"href": "#about"}),
                        _make_node("a", {"href": "#contact"}),
                    ],
                ),
                _make_node(
                    "section",
                    {"id": "hero", "data-section-index": "1"},
                    styles={"margin-top": "20px", "margin-bottom": "20px"},
                ),
                _make_node(
                    "section",
                    {"id": "about", "data-section-index": "2"},
                    styles={"margin-top": "20px"},
                    removable=False,
                ),
                _make_node(
                    "section",
                    {"id": "contact", "data-section-index": "3"},
                    styles={"margin-top": "20px"},
                ),
            ],
        )

        planner = SectionRemovalPlanner()

        # Test 1: Plan removal of removable section "hero"
        plan = planner.plan(root, "root > section:nth-child(2)")
        assert plan.section_node_path == "root > section:nth-child(2)"
        assert plan.container_type == LayoutContainerType.STACK
        assert len(plan.affected_siblings) == 3
        # Sibling "about" and "contact", plus the "nav"
        assert "root > nav:nth-child(1)" in plan.affected_siblings
        assert "root > section:nth-child(4)" in plan.affected_siblings

        # Sibling section renumber action + nav link remove action
        actions = plan.reflow_actions
        assert len(actions) == 4
        assert actions[0].action_type == "remove_nav_entry"
        assert actions[0].target_node_path == "root > nav:nth-child(1) > a:nth-child(1)"

        assert actions[1].action_type == "close_spacing_gap"
        assert actions[1].target_node_path == "root > nav:nth-child(1)"

        assert actions[2].action_type == "renumber_order"
        assert actions[2].target_node_path == "root > section:nth-child(3)"
        assert actions[2].after_value["data-section-index"] == "1"

        assert actions[3].action_type == "renumber_order"
        assert actions[3].target_node_path == "root > section:nth-child(4)"
        assert actions[3].after_value["data-section-index"] == "2"

        # Test 2: Error when planning non-removable section "about"
        with pytest.raises(ValueError, match="is marked non-removable"):
            planner.plan(root, "root > section:nth-child(3)")

        # Test 3: Error when targeting nodes inside a shadow root
        with pytest.raises(
            ValueError, match="Cannot target nodes inside a shadow root"
        ):
            planner.plan(root, "root > div:nth-child(1) > #shadow-root > a")


class TestGridReflow:
    def test_grid_resizing(self):
        # A 3-column grid container with 6 items (representing a portfolio card grid)
        grid_parent = _make_node(
            "div",
            styles={"display": "grid", "grid-template-columns": "repeat(3, 1fr)"},
            children=[
                _make_node("div", {"id": "item1"}),
                _make_node("div", {"id": "item2"}),
                _make_node("div", {"id": "item3"}),
                _make_node("div", {"id": "item4"}),
                _make_node("div", {"id": "item5"}),
                _make_node("div", {"id": "item6"}),
            ],
        )
        root = _make_node("div", children=[grid_parent])

        planner = SectionRemovalPlanner()
        # Plan removal of 6th item
        plan = planner.plan(root, "root > div:nth-child(1) > div:nth-child(6)")
        # Under the visual preservation policy, the column count remains unchanged to avoid jarring width jumps.
        # So no grid resize action is generated.
        assert len(plan.reflow_actions) == 0

        # Execute
        engine = LayoutReflowEngine()
        mutated = engine.execute(root, plan)
        mutated_grid = mutated.children[0]
        assert len(mutated_grid.children) == 5
        # Grid columns are preserved to maintain consistency, allowing a partial last row.
        assert mutated_grid.styles["grid-template-columns"] == "repeat(3, 1fr)"


class TestFlexReflow:
    def test_flex_redistribution(self):
        # Flex container with 3 items each occupying 33.3% width
        flex_parent = _make_node(
            "div",
            styles={"display": "flex", "flex-direction": "row"},
            children=[
                _make_node("div", styles={"width": "33.33%"}),
                _make_node("div", styles={"width": "33.33%"}),
                _make_node("div", styles={"width": "33.33%"}),
            ],
        )
        root = _make_node("div", children=[flex_parent])

        planner = SectionRemovalPlanner()
        # Plan removal of 3rd item
        plan = planner.plan(root, "root > div:nth-child(1) > div:nth-child(3)")

        # Generates flex recompute actions for remaining 2 items (should adjust to 50%)
        recompute_actions = [
            a for a in plan.reflow_actions if a.action_type == "recompute_flex_basis"
        ]
        assert len(recompute_actions) == 2
        for action in recompute_actions:
            assert action.after_value["width"] == "50.0%"

        # Execute
        engine = LayoutReflowEngine()
        mutated = engine.execute(root, plan)
        mutated_flex = mutated.children[0]
        assert len(mutated_flex.children) == 2
        for child in mutated_flex.children:
            assert child.styles["width"] == "50.0%"


class TestSpacingScale:
    def test_close_spacing_gap(self):
        # Vertical stack of 3 sections.
        # Sibling 1 has margin-bottom: 0px.
        # Sibling 2 (to be removed) has margin-top: 24px and margin-bottom: 32px.
        # Sibling 3 has margin-top: 24px.
        root = _make_node(
            "div",
            styles={"display": "block"},
            children=[
                _make_node("section", {"id": "sec1"}, styles={"margin-bottom": "0px"}),
                _make_node(
                    "section",
                    {"id": "sec2"},
                    styles={"margin-top": "24px", "margin-bottom": "32px"},
                ),
                _make_node("section", {"id": "sec3"}, styles={"margin-top": "24px"}),
            ],
        )

        planner = SectionRemovalPlanner()
        plan = planner.plan(root, "root > section:nth-child(2)")

        # Verify close_spacing_gap action transfers margin-bottom to sibling 1
        spacing_actions = [
            a for a in plan.reflow_actions if a.action_type == "close_spacing_gap"
        ]
        assert len(spacing_actions) == 1
        assert spacing_actions[0].target_node_path == "root > section:nth-child(1)"
        assert spacing_actions[0].after_value["margin-bottom"] == "32px"

        # Execute
        engine = LayoutReflowEngine()
        mutated = engine.execute(root, plan)
        assert len(mutated.children) == 2
        assert mutated.children[0].styles["margin-bottom"] == "32px"


class TestIntegrityValidator:
    @pytest.fixture
    def trees(self):
        # Setup valid original and mutated trees
        orig = _make_node(
            "div",
            children=[
                _make_node("nav", children=[_make_node("a", {"href": "#hero"})]),
                _make_node(
                    "section",
                    {"id": "hero", "data-section-index": "1"},
                    styles={"margin-bottom": "24px"},
                    slot_id="slot_hero",
                ),
                _make_node(
                    "section",
                    {"id": "about", "data-section-index": "2"},
                    styles={"margin-bottom": "24px"},
                    slot_id="slot_about",
                ),
            ],
        )

        # Correctly reflowed mutated tree (removed section 1 "hero" and its nav link, renumbered order)
        mutated_valid = _make_node(
            "div",
            children=[
                _make_node("nav", children=[]),
                _make_node(
                    "section",
                    {"id": "about", "data-section-index": "1"},
                    styles={"margin-bottom": "24px"},
                    slot_id="slot_about",
                ),
            ],
        )
        return orig, mutated_valid

    def test_positive_validation_passes(self, trees):
        orig, mutated_valid = trees
        validator = StructuralIntegrityValidator()
        report = validator.validate(orig, mutated_valid, "root > section:nth-child(2)")
        assert report.passed is True
        assert len(report.violations) == 0

    def test_orphaned_nav_violation(self, trees):
        orig, _ = trees
        # Nav link for #hero remains but section #hero is removed
        mutated_invalid = _make_node(
            "div",
            children=[
                _make_node("nav", children=[_make_node("a", {"href": "#hero"})]),
                _make_node(
                    "section",
                    {"id": "about", "data-section-index": "1"},
                    styles={"margin-bottom": "24px"},
                ),
            ],
        )
        validator = StructuralIntegrityValidator()
        report = validator.validate(
            orig, mutated_invalid, "root > section:nth-child(2)"
        )
        assert report.passed is False
        assert any(v.rule == "no_orphaned_nav_entries" for v in report.violations)

    def test_empty_grid_cells_violation(self, trees):
        orig, _ = trees
        # A grid container with 0 items (completely empty grid capacity)
        mutated_invalid = _make_node(
            "div",
            styles={"display": "grid", "grid-template-columns": "repeat(3, 1fr)"},
            children=[],
        )
        # Force dummy section path to avoid lookups
        orig_dummy = _make_node(
            "div", children=[_make_node("div", {"id": "removed_sec"})]
        )
        validator = StructuralIntegrityValidator()
        report = validator.validate(
            orig_dummy, mutated_invalid, "root > div:nth-child(1)"
        )
        assert report.passed is False
        assert any(v.rule == "no_empty_grid_cells" for v in report.violations)

    def test_contiguous_ordering_violation(self, trees):
        orig, _ = trees
        # Sibling index goes 1 then 3 (non-contiguous)
        mutated_invalid = _make_node(
            "div",
            children=[
                _make_node("section", {"id": "about", "data-section-index": "1"}),
                _make_node("section", {"id": "contact", "data-section-index": "3"}),
            ],
        )
        orig_dummy = _make_node(
            "div", children=[_make_node("section", {"id": "removed_sec"})]
        )
        validator = StructuralIntegrityValidator()
        report = validator.validate(
            orig_dummy, mutated_invalid, "root > section:nth-child(1)"
        )
        assert report.passed is False
        assert any(v.rule == "contiguous_section_ordering" for v in report.violations)

    def test_spacing_scale_violation(self, trees):
        orig, _ = trees
        # Spacing of 999px falls outside of original scale (which only has 24px)
        mutated_invalid = _make_node(
            "div",
            children=[
                _make_node(
                    "section", {"id": "about"}, styles={"margin-bottom": "999px"}
                ),
            ],
        )
        validator = StructuralIntegrityValidator()
        report = validator.validate(
            orig, mutated_invalid, "root > section:nth-child(2)"
        )
        assert report.passed is False
        assert any(v.rule == "spacing_scale_invariance" for v in report.violations)

    def test_dangling_slot_id_violation(self, trees):
        orig, _ = trees
        # Sibling node retains reference to slot_hero which was part of the removed section
        mutated_invalid = _make_node(
            "div",
            children=[
                _make_node(
                    "section",
                    {"id": "about", "data-section-index": "1"},
                    styles={"margin-bottom": "24px"},
                    slot_id="slot_hero",
                ),
            ],
        )
        validator = StructuralIntegrityValidator()
        report = validator.validate(
            orig, mutated_invalid, "root > section:nth-child(2)"
        )
        assert report.passed is False
        assert any(v.rule == "no_dangling_slot_references" for v in report.violations)


class TestShadowDOMBoundary:
    def test_shadow_dom_atomic_boundaries(self):
        # Tree containing a shadow host
        shadow_content = _make_node(
            "div",
            children=[
                _make_node("h1", text="Inside Shadow"),
            ],
        )
        shadow_host = _make_node(
            "my-widget", {"id": "host"}, shadow_root=shadow_content
        )
        root = _make_node(
            "div",
            children=[
                _make_node("section", {"id": "hero"}),
                shadow_host,
                _make_node("section", {"id": "contact"}),
            ],
        )

        planner = SectionRemovalPlanner()
        # 1. Removing a section adjacent to the shadow host is allowed and plans normally
        plan = planner.plan(root, "root > section:nth-child(1)")
        assert plan.section_node_path == "root > section:nth-child(1)"
        assert len(plan.reflow_actions) == 0  # no dependencies

        # 2. Reflow engine executes and moves shadow host as a whole
        engine = LayoutReflowEngine()
        mutated = engine.execute(root, plan)
        assert len(mutated.children) == 2
        assert (
            mutated.children[0].tag == "my-widget"
        )  # host correctly repositioned to index 0
        assert mutated.children[0].shadow_root is not None
        assert (
            mutated.children[0].shadow_root.children[0].tag == "h1"
        )  # interior untouched


class TestRollbackAndDiff:
    def test_immutability_and_versioning(self):
        orig = _make_node(
            "div",
            children=[
                _make_node("section", {"id": "hero"}),
                _make_node("section", {"id": "about"}),
            ],
        )
        planner = SectionRemovalPlanner()
        plan = planner.plan(orig, "root > section:nth-child(1)")

        engine = LayoutReflowEngine()
        mutated = engine.execute(orig, plan)

        # Confirm original remains unmodified
        assert len(orig.children) == 2
        assert len(mutated.children) == 1

        # Confirm versioning snapshot diffing works
        with tempfile.TemporaryDirectory() as tmpdir:
            versioning = TemplateVersioning(tmpdir)

            # Save original as version 1
            v1 = versioning.save_version("test_site", orig.model_dump())
            assert v1 == 1

            # Save mutated as version 2
            v2 = versioning.save_version("test_site", mutated.model_dump())
            assert v2 == 2

            # Roll back version 2 to version 1
            restored = versioning.get_version("test_site", 1)
            assert restored["data"]["children"][0]["attributes"]["id"] == "hero"


class TestEndToEndRemovalOrchestration:
    def test_remove_sections_pipeline(self):
        # Write a dummy run directory structure
        with tempfile.TemporaryDirectory() as base_dir:
            router = ExecutionRouter()
            router.storage.base_dir = base_dir

            # Setup a run ID
            run_id = "test_run"
            run_dir = os.path.join(base_dir, run_id)
            os.makedirs(run_dir, exist_ok=True)

            # Create a valid CIDS template fixture
            cids_root = _make_node(
                "div",
                children=[
                    _make_node("nav", children=[_make_node("a", {"href": "#hero"})]),
                    _make_node(
                        "section",
                        {"id": "hero", "data-section-index": "1"},
                        styles={"margin-bottom": "24px"},
                        slot_id="slot_hero",
                    ),
                    _make_node(
                        "section",
                        {"id": "about", "data-section-index": "2"},
                        styles={"margin-bottom": "24px"},
                        slot_id="slot_about",
                    ),
                ],
            )
            cids = CanonicalDesignSchema(
                url="http://test.com",
                root=cids_root,
                tokens=DesignTokens(spacing={"md": "24px"}),
            )

            # Save initial cids schema
            with open(
                os.path.join(run_dir, "schema_cids.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(cids.model_dump(), f, indent=2)

            # Call remove_sections to remove "hero"
            result = router.remove_sections(run_id, ["root > section:nth-child(2)"])

            assert result.integrity_report.passed is True
            assert result.recompilation_triggered is True
            assert len(result.mutated_root.children) == 2  # nav + section about
            assert result.mutated_root.children[1].attributes["id"] == "about"
            assert (
                result.mutated_root.children[1].attributes["data-section-index"] == "1"
            )

            # Verify compilers generated React/Vue code successfully
            assert os.path.exists(os.path.join(run_dir, "output_react.jsx"))
            assert os.path.exists(os.path.join(run_dir, "output_vue.vue"))

            # Verify React output compiles safely and strips XSS if any (sanitization runs automatically)
            with open(
                os.path.join(run_dir, "output_react.jsx"), "r", encoding="utf-8"
            ) as f:
                react_code = f.read()
            assert "dangerouslySetInnerHTML" not in react_code  # confirm sanitized
