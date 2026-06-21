import pytest
import os
import json
import asyncio
from wire.agents.observation.browser_session import BrowserSession
from wire.agents.observation.shadow_piercer import ShadowPiercer
from wire.schema.canonical import HTMLToCidsParser, ComponentNode
from wire.schema.input_blueprint import InputBlueprint, DataSlot, SlotConstraint
from wire.synthesis.knowledge_index import KnowledgeIndex
from wire.synthesis.prompt_generator import PromptGenerator
from bs4 import BeautifulSoup

@pytest.fixture
def shadow_fixture_url():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    fixture_path = os.path.join(current_dir, "fixtures", "shadow_target.html")
    return "file:///" + fixture_path.replace("\\", "/")

@pytest.mark.slow
@pytest.mark.asyncio
async def test_wait_for_dom_stability():
    session = BrowserSession()
    await session.start()
    page = await session.context.new_page()
    try:
        # Load a blank page and dynamically change body content via js delay
        await page.goto("about:blank")
        
        # Start a background task that adds elements after a short delay
        async def add_dynamic_nodes():
            await asyncio.sleep(0.5)
            await page.evaluate("() => { document.body.innerHTML += '<div>Dynamic 1</div>'; }")
            await asyncio.sleep(0.5)
            await page.evaluate("() => { document.body.innerHTML += '<div>Dynamic 2</div>'; }")

        task = asyncio.create_task(add_dynamic_nodes())
        
        # Wait for stability should complete successfully after the content stops updating
        await session.wait_for_dom_stability(page, timeout_ms=3000, check_interval_ms=200)
        await task
        
        text = await page.inner_text("body")
        assert "Dynamic 2" in text
    finally:
        await page.close()
        await session.stop()

@pytest.mark.slow
@pytest.mark.asyncio
async def test_shadow_dom_piercer_and_cids_mapping(shadow_fixture_url):
    session = BrowserSession()
    await session.start()
    page = await session.context.new_page()
    try:
        await page.goto(shadow_fixture_url, wait_until="networkidle")
        
        # 1. Test Shadow DOM extraction
        piercer = ShadowPiercer()
        shadow_content = await piercer.extract_shadow_content(page)
        
        # We should find two hosts: my-element and nested-element
        assert len(shadow_content) >= 2
        
        # Verify host paths are css paths
        paths = [e["host_path"] for e in shadow_content]
        assert any("host1" in p for p in paths)
        
        # Verify structure of host 1's shadow tree
        host1_entry = next(e for e in shadow_content if "host1" in e["host_path"])
        shadow_tree = host1_entry["shadow_tree"]
        assert shadow_tree["tag"] == "#shadow-root"
        assert shadow_tree["style_provenance"] == "cascade_resolved"
        
        # Find shadow box div
        children = shadow_tree["children"]
        div_node = next(c for c in children if c["tag"] == "div")
        assert "shadow-box" in div_node["attributes"].get("class", "")
        # Scoped style resolution: color should match custom style
        assert div_node["styles"].get("color") == "rgb(255, 0, 0)"
        
        # Find span inside shadow root
        span_node = next(c for c in div_node["children"] if c["tag"] == "span")
        assert span_node["styles"].get("font-size") == "16px"
        
        # Find nested shadow root
        nested_element_node = next(c for c in div_node["children"] if c["tag"] == "nested-element")
        assert nested_element_node["shadow_root"] is not None
        assert nested_element_node["shadow_root"]["style_provenance"] == "cascade_resolved"
        
        # Verify adoptedStyleSheets mapping
        nested_p = next(c for c in nested_element_node["shadow_root"]["children"] if c["tag"] == "p")
        assert nested_p["styles"].get("color") == "rgb(0, 0, 255)"

        # 2. Test integration/mapping into CIDS parser
        # Build bs4 soup from page content (host elements will be present)
        content = await page.content()
        soup = BeautifulSoup(content, 'lxml')
        
        # Build shadow_roots_map in memory
        shadow_roots_map = {}
        from wire.schema.canonical import ComponentNode
        def dict_to_node(d: dict) -> ComponentNode:
            if not d:
                return None
            child_nodes = [dict_to_node(c) for c in d.get("children", []) if c]
            shadow_root = dict_to_node(d["shadow_root"]) if d.get("shadow_root") else None
            return ComponentNode(
                tag=d.get("tag", "div"),
                attributes=d.get("attributes", {}),
                styles=d.get("styles", {}),
                children=child_nodes,
                shadow_root=shadow_root,
                style_provenance=d.get("style_provenance"),
                text_content=d.get("text_content")
            )

        for entry in shadow_content:
            shadow_roots_map[entry["host_path"]] = dict_to_node(entry["shadow_tree"])
            
        # Parse BS4 soup into CIDS
        real_root = HTMLToCidsParser.parse(soup, style_map={}, interactions_map={}, shadow_roots_map=shadow_roots_map)
        
        # Find my-element in the parsed tree
        def find_node(node: ComponentNode, tag_name: str):
            if node.tag == tag_name:
                return node
            for child in node.children:
                found = find_node(child, tag_name)
                if found:
                    return found
            return None
            
        my_element_node = find_node(real_root, "my-element")
        assert my_element_node is not None
        assert my_element_node.shadow_root is not None
        assert my_element_node.shadow_root.tag == "#shadow-root"
        assert my_element_node.shadow_root.style_provenance == "cascade_resolved"
        
        # Coexistence Boundary test (amendment 1):
        # Parent host has cascade-resolved styles mapped externally, children inside have shadow-root resolved styles
        # Let's map parent styles
        styles_map = {id(soup.select_one("my-element")): {"border": "1px solid black"}}
        real_root_styled = HTMLToCidsParser.parse(soup, style_map=styles_map, interactions_map={}, shadow_roots_map=shadow_roots_map)
        styled_my_element = find_node(real_root_styled, "my-element")
        assert styled_my_element.styles.get("border") == "1px solid black"
        assert styled_my_element.shadow_root is not None
        assert styled_my_element.shadow_root.children[0].tag == "div"  # shadow-box div

    finally:
        await page.close()
        await session.stop()

def test_input_blueprint_validation():
    # Construct input blueprint with required/optional slots
    blueprint = InputBlueprint(
        slots={
            "required_title": DataSlot(
                id="required_title",
                type="text",
                constraint=SlotConstraint(allowed_types=["text"], max_length=50),
                required=True
            ),
            "optional_desc": DataSlot(
                id="optional_desc",
                type="text",
                constraint=SlotConstraint(allowed_types=["text"], max_length=200),
                required=False
            ),
            "required_hero": DataSlot(
                id="required_hero",
                type="image",
                constraint=SlotConstraint(allowed_types=["image"], max_width=1200),
                required=True
            ),
            "optional_avatar": DataSlot(
                id="optional_avatar",
                type="image",
                constraint=SlotConstraint(allowed_types=["image"]),
                required=False
            )
        }
    )

    # Test Case 1: All Valid Inputs (No Warnings)
    inputs_valid = {
        "required_title": "Welcome to AVS",
        "optional_desc": "AVS Engineering College description.",
        "required_hero": "assets/hero.jpg",
        "optional_avatar": "assets/avatar.png"
    }
    report = blueprint.generate_summary_report(inputs_valid)
    assert report["is_valid"] is True
    assert len(report["hard_failures"]) == 0
    assert len(report["soft_warnings"]) == 0
    assert len(report["successes"]) == 4

    # Test Case 2: Required missing (Hard Failure)
    inputs_missing_req = {
        "optional_desc": "AVS description",
        "required_hero": "assets/hero.jpg"
    }
    report = blueprint.generate_summary_report(inputs_missing_req)
    assert len(report["hard_failures"]) == 1
    # Wait, in generate_summary_report:
    # for slot_id, slot in self.slots.items():
    #   val = inputs.get(slot_id)
    #   res = validate_input(slot_id, val)
    # optional_avatar is missing (val=None). optional is not required, so:
    # validate_input returns valid=True, severity="soft", message="Optional slot... is empty."
    # So optional_avatar is in soft_warnings.
    # required_title is missing (val=None) and required. validate_input returns valid=False.
    # So required_title is in hard_failures.
    # Total hard: 1 (required_title).
    assert any(f["slot_id"] == "required_title" for f in report["hard_failures"])

    # Test Case 3: Type Mismatch (Hard Failure)
    inputs_type_mismatch = {
        "required_title": 12345,  # Expected string
        "required_hero": "assets/hero.jpg"
    }
    report = blueprint.generate_summary_report(inputs_type_mismatch)
    assert report["is_valid"] is False
    assert any(f["slot_id"] == "required_title" and "Type mismatch" in f["message"] for f in report["hard_failures"])

    # Test Case 4: Soft warnings (Length exceeded, placeholder patterns)
    inputs_soft_warnings = {
        "required_title": "A" * 60,  # Exceeds max_length=50
        "optional_desc": "Lorem Ipsum placeholder content.",  # Placeholder pattern
        "required_hero": "assets/default_placeholder.jpg",  # Placeholder image
        "optional_avatar": {"path": "assets/avatar.jpg", "width": 800, "height": 800}
    }
    report = blueprint.generate_summary_report(inputs_soft_warnings)
    assert report["is_valid"] is True  # Soft warning does NOT block compilation!
    assert len(report["hard_failures"]) == 0
    assert len(report["soft_warnings"]) == 3
    
    warnings = [w["slot_id"] for w in report["soft_warnings"]]
    assert "required_title" in warnings  # length exceeded
    assert "optional_desc" in warnings   # lorem ipsum
    assert "required_hero" in warnings   # placeholder image name

def test_knowledge_index_enhanced_queries():
    index = KnowledgeIndex(index_dir="output/temp_test_index")
    index.entries = [
        {"url": "http://test.com", "category": "colors", "key": "primary", "value": "#ff0000"},
        {"url": "http://test.com", "category": "colors", "key": "secondary", "value": "#ff1010"}, # very close to primary
        {"url": "http://test.com", "category": "colors", "key": "background", "value": "#000000"}, # black
        {"url": "http://test.com", "category": "typography", "key": "heading-font", "value": "Inter Sans-serif"},
        {"url": "http://test.com", "category": "spacing", "key": "md", "value": "16px"},
    ]

    # Token match query
    res_token = index.query(token_match="sans-serif")
    assert len(res_token) == 1
    assert res_token[0]["key"] == "heading-font"

    # Color similarity query
    # Target color #ff0505 (very close to #ff0000 and #ff1010)
    res_color = index.query(color_similarity_target="#ff0505", color_similarity_threshold=20.0)
    assert len(res_color) == 2
    keys = [e["key"] for e in res_color]
    assert "primary" in keys
    assert "secondary" in keys
    assert "background" not in keys

def test_prompt_generator_structured_prompts():
    gen = PromptGenerator()
    data = {
        "colors": {"primary": "#ff0000", "background": "#ffffff"},
        "typography": {"base": "Inter"},
        "spacing": {"md": "16px"}
    }
    prompts = gen.generate_prompts(data, "http://test.com")
    
    full_prompt = next(p["prompt"] for p in prompts if p["id"] == "full_regeneration")
    assert "SLOT BINDING CONTRACT" in full_prompt
    assert "DESIGN SYSTEM GUIDELINES" in full_prompt

@pytest.mark.slow
@pytest.mark.asyncio
async def test_mixed_provenance_boundary(shadow_fixture_url):
    session = BrowserSession()
    await session.start()
    page = await session.context.new_page()
    try:
        await page.goto(shadow_fixture_url, wait_until="networkidle")
        
        # Pierce shadow DOM
        piercer = ShadowPiercer()
        shadow_content = await piercer.extract_shadow_content(page)
        
        # Parse BS4 soup
        content = await page.content()
        soup = BeautifulSoup(content, 'lxml')
        
        shadow_roots_map = {}
        from wire.schema.canonical import ComponentNode
        def dict_to_node(d: dict) -> ComponentNode:
            if not d:
                return None
            child_nodes = [dict_to_node(c) for c in d.get("children", []) if c]
            shadow_root = dict_to_node(d["shadow_root"]) if d.get("shadow_root") else None
            return ComponentNode(
                tag=d.get("tag", "div"),
                attributes=d.get("attributes", {}),
                styles=d.get("styles", {}),
                children=child_nodes,
                shadow_root=shadow_root,
                style_provenance=d.get("style_provenance"),
                text_content=d.get("text_content")
            )

        for entry in shadow_content:
            shadow_roots_map[entry["host_path"]] = dict_to_node(entry["shadow_tree"])
            
        # Parse into CIDS
        real_root = HTMLToCidsParser.parse(soup, style_map={}, interactions_map={}, shadow_roots_map=shadow_roots_map)
        
        # Helpers to find nodes
        def find_node(node: ComponentNode, tag_name: str):
            if node.tag == tag_name:
                return node
            for child in node.children:
                found = find_node(child, tag_name)
                if found:
                    return found
            return None

        # 1. Assert host1 (my-element) is present and has cascade_resolved provenance
        host1_node = find_node(real_root, "my-element")
        assert host1_node is not None
        assert host1_node.shadow_root is not None
        assert host1_node.shadow_root.style_provenance == "cascade_resolved"
        
        # Verify host1 style values are correct and uncorrupted
        host1_div = host1_node.shadow_root.children[0]
        assert host1_div.tag == "div"
        assert host1_div.styles.get("color") == "rgb(255, 0, 0)"
        assert host1_div.styles.get("background-color") == "rgb(0, 255, 0)"
        
        # Verify nested shadow child inside host1 (adopted stylesheet resolution)
        nested_element = host1_div.children[1]
        assert nested_element.tag == "nested-element"
        assert nested_element.shadow_root is not None
        assert nested_element.shadow_root.style_provenance == "cascade_resolved"
        nested_p = nested_element.shadow_root.children[0]
        assert nested_p.tag == "p"
        assert nested_p.styles.get("color") == "rgb(0, 0, 255)"
        
        # 2. Assert host2 (closed-element) is present and has computed_fallback provenance
        host2_node = find_node(real_root, "closed-element")
        assert host2_node is not None
        assert host2_node.shadow_root is not None
        assert host2_node.shadow_root.style_provenance == "computed_fallback"
        
        # Verify host2 style values are correct and not contaminated
        closed_div = host2_node.shadow_root.children[0]
        assert closed_div.tag == "div"
        assert closed_div.styles.get("color") == "rgb(0, 128, 0)"
        # Confirm host2 didn't inherit/leak background-color from host1's styles
        assert "background-color" not in closed_div.styles or closed_div.styles.get("background-color") != "rgb(0, 255, 0)"
    finally:
        await page.close()
        await session.stop()

@pytest.mark.slow
@pytest.mark.asyncio
async def test_shadow_dom_visual_fidelity(shadow_fixture_url):
    session = BrowserSession()
    await session.start()
    page = await session.context.new_page()
    try:
        from wire.orchestrator.execution_router import ExecutionRouter
        from wire.storage.local import LocalStorage
        
        # 1. Run pipeline components end-to-end on the fixture
        await page.goto(shadow_fixture_url, wait_until="networkidle")
        
        # Pierce shadow DOM
        piercer = ShadowPiercer()
        shadow_content = await piercer.extract_shadow_content(page)
        
        # Capture and rewrite HTML
        content = await page.content()
        from wire.agents.extraction.asset_downloader import AssetDownloader
        downloader = AssetDownloader()
        storage = LocalStorage()
        storage.initialize_for_url(shadow_fixture_url)
        rewritten_content, assets = await downloader.download_assets(
            shadow_fixture_url, content, storage.get_asset_path()
        )
        
        # Cascade resolution
        from wire.schema.style_mapper import CascadeResolver
        resolver = CascadeResolver()
        soup_with_cascade, styles_map = resolver.resolve(rewritten_content, "")
        
        # Map shadow DOM structures
        shadow_roots_map = {}
        from wire.schema.canonical import ComponentNode
        def dict_to_node(d: dict) -> ComponentNode:
            if not d:
                return None
            child_nodes = [dict_to_node(c) for c in d.get("children", []) if c]
            shadow_root = dict_to_node(d["shadow_root"]) if d.get("shadow_root") else None
            return ComponentNode(
                tag=d.get("tag", "div"),
                attributes=d.get("attributes", {}),
                styles=d.get("styles", {}),
                children=child_nodes,
                shadow_root=shadow_root,
                style_provenance=d.get("style_provenance"),
                text_content=d.get("text_content")
            )

        for entry in shadow_content:
            shadow_roots_map[entry["host_path"]] = dict_to_node(entry["shadow_tree"])
            
        # Parse into CIDS
        real_root = HTMLToCidsParser.parse(soup_with_cascade, styles_map, interactions_map={}, shadow_roots_map=shadow_roots_map)
        from wire.schema.canonical import CanonicalDesignSchema, DesignTokens
        cids = CanonicalDesignSchema(
            url=shadow_fixture_url,
            tokens=DesignTokens(),
            root=real_root
        )
        
        # Compile back to HTML
        from wire.compilers.html_compiler import HTMLCompiler
        compiler = HTMLCompiler()
        reconstructed_html = compiler.compile(cids)
        
        # Write to temporary output file
        out_dir = "output"
        os.makedirs(out_dir, exist_ok=True)
        recon_path = os.path.join(out_dir, "shadow_reconstructed.html")
        with open(recon_path, "w", encoding="utf-8") as f:
            f.write(reconstructed_html)
            
        recon_url = "file:///" + os.path.abspath(recon_path).replace("\\", "/")
        
        # 2. Capture screenshots of isolated shadow-rendered region (#host1)
        # Original page screenshot
        await page.goto(shadow_fixture_url, wait_until="networkidle")
        host1 = await page.query_selector("#host1")
        bbox1 = await host1.bounding_box()
        orig_img_path = os.path.join(out_dir, "shadow_original_host1.png")
        await page.screenshot(path=orig_img_path, clip=bbox1)
        
        # Reconstructed page screenshot
        await page.goto(recon_url, wait_until="networkidle")
        # Give Declarative Shadow DOM time to render
        await page.wait_for_timeout(500)
        host2 = await page.query_selector("#host1")
        bbox2 = await host2.bounding_box()
        recon_img_path = os.path.join(out_dir, "shadow_reconstructed_host1.png")
        await page.screenshot(path=recon_img_path, clip=bbox2)
        
        # 3. Run visual diff
        from wire.validation.visual_diff import VisualDiff
        diff_engine = VisualDiff()
        result = diff_engine.compare_screenshots(orig_img_path, recon_img_path)
        similarity = result["similarity_percent"]
        
        print(f"\n--- SHADOW DOM VISUAL FIDELITY: {similarity}% ---")
        assert similarity >= 95.0, f"Shadow DOM visual fidelity ({similarity}%) is below 95% threshold"
        
    finally:
        await page.close()
        await session.stop()
