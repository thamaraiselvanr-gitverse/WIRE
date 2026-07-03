import json
import os
import tempfile

from wire.orchestrator.execution_router import ExecutionRouter
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode, DesignTokens
from wire.templates.tokens import DesignTokenSystem


def test_apply_palette_remaps_by_role_preserving_format():
    system = DesignTokenSystem(tempfile.mkdtemp())
    node = ComponentNode(
        tag="div",
        styles={"color": "rgb(255, 0, 0)", "background-color": "#ffffff"},
        children=[ComponentNode(tag="span", styles={"color": "#ff0000"})],
    )
    # From red/white -> to blue/black by role.
    from_tokens = {"colors": {"primary": "#ff0000", "background": "#ffffff"}}
    to_tokens = {"colors": {"primary": "#0000ff", "background": "#000000"}}

    out = system.apply_palette(node, to_tokens, from_tokens)
    # rgb() input keeps rgb() format; hex input keeps hex format.
    assert out.styles["color"] == "rgb(0, 0, 255)"
    assert out.styles["background-color"] == "#000000"
    assert out.children[0].styles["color"] == "#0000ff"
    # Original is untouched (deep-copied).
    assert node.styles["color"] == "rgb(255, 0, 0)"


def test_apply_brand_end_to_end_recompiles_outputs():
    with tempfile.TemporaryDirectory() as base_dir:
        router = ExecutionRouter()
        router.storage.base_dir = base_dir
        run_id = "brand_run"
        run_dir = os.path.join(base_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)

        root = ComponentNode(
            tag="body",
            children=[
                ComponentNode(
                    tag="header",
                    attributes={"class": "hero"},
                    styles={"background-color": "#ff0000", "color": "#ffffff"},
                    children=[ComponentNode(tag="#text", text_content="Title")],
                )
            ],
        )
        cids = CanonicalDesignSchema(
            url="http://demo.com",
            root=root,
            tokens=DesignTokens(colors={"primary": "#ff0000", "background": "#ffffff"}),
        )
        with open(
            os.path.join(run_dir, "schema_cids.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(cids.model_dump(), f)

        brand = {"colors": {"primary": "#0000ff", "background": "#000000"}}
        result = router.apply_brand(run_id, brand)

        assert result["success"] is True
        assert result["colors_remapped"] == 2
        assert result["recompilation_triggered"] is True

        # CIDS on disk now carries the brand palette.
        with open(os.path.join(run_dir, "schema_cids.json"), encoding="utf-8") as f:
            restyled = json.load(f)
        header = restyled["root"]["children"][0]
        assert header["styles"]["background-color"] == "#0000ff"
        assert header["styles"]["color"] == "#000000"
        assert restyled["tokens"]["colors"]["primary"] == "#0000ff"

        # All three outputs were regenerated with the new palette.
        for name in ("output_editable.html", "output_react.jsx", "output_vue.vue"):
            path = os.path.join(run_dir, name)
            assert os.path.exists(path)
            assert "#0000ff" in open(path, encoding="utf-8").read()


def test_apply_brand_missing_run_raises():
    with tempfile.TemporaryDirectory() as base_dir:
        router = ExecutionRouter()
        router.storage.base_dir = base_dir
        try:
            router.apply_brand("nonexistent", {"colors": {"primary": "#000000"}})
            assert False, "expected ValueError"
        except ValueError as e:
            assert "not found" in str(e)
