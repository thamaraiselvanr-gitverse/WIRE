import os
import tempfile
import json
import pytest
from wire.compilers.sanitizer import HtmlSanitizer
from wire.schema.canonical import HTMLToCidsParser, ComponentNode, CanonicalDesignSchema, DesignTokens
from wire.compilers.html_compiler import HTMLCompiler
from wire.compilers.react_adapter import ReactAdapter
from wire.compilers.vue_adapter import VueAdapter
from wire.templates.registry import TemplateRegistry
from wire.templates.tokens import DesignTokenSystem
from wire.templates.artifact import WireArtifact
from wire.templates.composer import TemplateComposer
from wire.templates.versioning import TemplateVersioning
from wire.templates.preview import TemplatePreview

# ==========================================
# 1. HTML Sanitizer & Centralized CIDS Tests
# ==========================================

def test_html_sanitizer_rules():
    raw_html = """
    <div>
        <script>alert('evil')</script>
        <iframe src="http://example.com"></iframe>
        <span onclick="runEvilCode()" id="safe-span">Hello</span>
        <a href="javascript:void(0)" id="bad-link">Click here</a>
        <a href="https://example.com" id="good-link">Safe Link</a>
        <div style="color: red; expression(alert(1)); behavior: url(x); background: url(javascript:alert(2))" id="styled">Content</div>
    </div>
    """
    sanitized = HtmlSanitizer.sanitize_html(raw_html)
    
    assert "<script>" not in sanitized
    assert "iframe" not in sanitized
    assert "onclick" not in sanitized
    assert "javascript:" not in sanitized
    assert "expression" not in sanitized
    assert "behavior" not in sanitized
    assert "safe-span" in sanitized
    assert "good-link" in sanitized
    assert "color: red" in sanitized


def test_centralized_sanitization_at_cids_level():
    """
    CRITICAL SECURITY CHECK:
    Asserts that sanitization is performed directly at the CIDS tree level,
    meaning the ComponentNode tree itself is clean by construction.
    """
    dirty_html = """
    <div id="root">
        <script>console.log('xss')</script>
        <span onclick="evil()" id="host">Safe Text</span>
        <a href="javascript:evil()" id="link">Link</a>
    </div>
    """
    
    # Parse the dirty HTML into CIDS tree
    root_node = HTMLToCidsParser.parse(dirty_html)
    
    def find_node(node: ComponentNode, tag_name: str, node_id: str = None) -> ComponentNode | None:
        if node.tag == tag_name:
            if not node_id or node.attributes.get("id") == node_id:
                return node
        for child in node.children:
            res = find_node(child, tag_name, node_id)
            if res:
                return res
        return None

    def count_nodes(node: ComponentNode, tag_name: str) -> int:
        count = 1 if node.tag == tag_name else 0
        for child in node.children:
            count += count_nodes(child, tag_name)
        return count

    # 1. Verify script tag node is completely excluded from tree
    assert count_nodes(root_node, "script") == 0, "Script tag node was not stripped at CIDS tree level"
    
    # 2. Verify span node exists but has no onclick event handlers in attributes
    span_node = find_node(root_node, "span", "host")
    assert span_node is not None, "Span node not found"
    assert "onclick" not in span_node.attributes, "Event handler attribute was not stripped at CIDS tree level"
    
    # 3. Verify link node exists but has no href starting with javascript:
    link_node = find_node(root_node, "a", "link")
    assert link_node is not None, "Link node not found"
    assert "href" not in link_node.attributes, "Unsafe href protocol was not stripped at CIDS tree level"


def test_compiler_defense_in_depth_sanitization():
    # Construct a CIDS ComponentNode that has bypass attributes injected (simulating manual modification)
    bypass_node = ComponentNode(
        tag="div",
        attributes={"onclick": "evil()", "id": "test", "href": "javascript:alert(1)"},
        styles={"color": "red", "background": "url(javascript:alert(2))"},
        text_content="content"
    )
    cids = CanonicalDesignSchema(
        url="http://test.com",
        tokens=DesignTokens(colors={"primary": "#ff0000"}),
        root=bypass_node
    )
    
    # 1. HTML Compiler
    html_out = HTMLCompiler().compile(cids)
    assert "onclick" not in html_out
    assert "javascript:" not in html_out
    
    # 2. React Adapter
    react_out = ReactAdapter().compile(cids)
    assert "onclick" not in react_out
    assert "javascript:" not in react_out
    
    # 3. Vue Adapter
    vue_out = VueAdapter().compile(cids)
    assert "onclick" not in vue_out
    assert "javascript:" not in vue_out

# ==========================================
# 2. Registry, Tokens, Composer & Versioning Tests
# ==========================================

def test_template_registry_multi_tag_and_ranking():
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = TemplateRegistry(tmpdir)
        
        # Register templates
        registry.register("t1", "http://site1.com", ["landing", "ecommerce"], {"rank": 5})
        registry.register("t2", "http://site2.com", ["landing", "blog"], {"rank": 10})
        registry.register("t3", "http://site3.com", ["portfolio", "blog"], {"rank": 2})
        
        # Test multi-tag search (match_all=True)
        results = registry.search_by_tags(["landing", "ecommerce"], match_all=True)
        assert len(results) == 1
        assert results[0]["id"] == "t1"
        
        # Test multi-tag search (match_all=False) - sorted by rank
        results = registry.search_by_tags(["blog", "landing"], match_all=False)
        assert len(results) == 3
        # t2 has rank 10, t1 has rank 5 (via landing match), t3 has rank 2
        assert results[0]["id"] == "t2"
        assert results[1]["id"] == "t1"
        assert results[2]["id"] == "t3"
        
        # Boost t3 rank
        registry.boost_rank("t3", amount=15) # t3 rank becomes 2 + 15 = 17
        results = registry.search_by_tags(["blog", "landing"], match_all=False)
        assert results[0]["id"] == "t3"


def test_token_swap_substitution():
    with tempfile.TemporaryDirectory() as tmpdir:
        system = DesignTokenSystem(tmpdir)
        
        # Create design tokens for source and target
        system.save_tokens("siteA", {"colors": {"primary": "#0000ff", "background": "#000000"}}) # Blue, Black
        system.save_tokens("siteB", {"colors": {"primary": "#ff0000", "background": "#ffffff"}}) # Red, White
        
        # Target node has red text color and white background
        target_node = ComponentNode(
            tag="div",
            styles={"color": "rgb(255, 0, 0)", "background-color": "rgb(255, 255, 255)"},
            children=[
                ComponentNode(tag="span", styles={"color": "#ff0000"})
            ]
        )
        
        # Apply swap: Site B (red/white) -> Site A (blue/black)
        swapped = system.swap_tokens_in_cids(target_node, "siteA", "siteB")
        
        # rgb(255, 0, 0) should be Blue rgb(0, 0, 255) / #0000ff
        assert swapped.styles.get("color") == "rgb(0, 0, 255)"
        # rgb(255, 255, 255) should be Black rgb(0, 0, 0) / #000000
        assert swapped.styles.get("background-color") == "rgb(0, 0, 0)"
        # Child span style #ff0000 should be #0000ff
        assert swapped.children[0].styles.get("color") == "#0000ff"


def test_template_composer_collision_and_nesting():
    composer = TemplateComposer()
    
    # 1. Test collision resolution
    components = [
        {"id": "header", "tag": "div", "content": "Welcome", "source_template": "site1"},
        {"id": "header", "tag": "div", "content": "Navbar", "source_template": "site2"}
    ]
    
    composed = composer.compose(components)
    assert composed["component_count"] == 2
    assert composed["components"][0]["id"] == "header"
    assert composed["components"][1]["id"] == "site2_header" # ID Collision namespaced!
    
    # 2. Test nesting validation (block node inside inline node warning)
    bad_nesting_components = [
        {"id": "span_parent", "tag": "span", "content": "<div>Block inside Span!</div>"}
    ]
    composed_bad = composer.compose(bad_nesting_components)
    assert len(composed_bad["errors"]) > 0
    assert "Invalid HTML nesting" in composed_bad["errors"][0]


def test_template_versioning_diff_and_rollback():
    with tempfile.TemporaryDirectory() as tmpdir:
        versioning = TemplateVersioning(tmpdir)
        
        cids_v1 = {
            "url": "http://site.com",
            "root": {
                "tag": "div",
                "styles": {"color": "red"},
                "children": [
                    {"tag": "span", "text_content": "v1 content"}
                ]
            }
        }
        
        cids_v2 = {
            "url": "http://site.com",
            "root": {
                "tag": "div",
                "styles": {"color": "blue"}, # Changed style
                "children": [
                    {"tag": "span", "text_content": "v2 content"}, # Changed text
                    {"tag": "button", "text_content": "Click"} # Added node
                ]
            }
        }
        
        # Save versions
        v1 = versioning.save_version("temp1", cids_v1)
        v2 = versioning.save_version("temp2", cids_v2)
        
        assert v1 == 1
        assert v2 == 1
        
        # Save as same template ID to test diffs
        v1 = versioning.save_version("siteX", cids_v1)
        v2 = versioning.save_version("siteX", cids_v2)
        
        assert v1 == 1
        assert v2 == 2
        
        diff_res = versioning.diff("siteX", 1, 2)
        
        # Verify details of structural CIDS diff
        added_paths = diff_res["details"]["added"].keys()
        changed_paths = diff_res["details"]["changed"].keys()
        
        assert any("button" in p for p in added_paths)
        assert any("styles.color" in p for p in changed_paths)
        assert any("text" in p for p in changed_paths)
        
        # Test rollback
        rolled_back = versioning.rollback("siteX", 1)
        assert rolled_back["root"]["styles"]["color"] == "red"

# ==========================================
# 3. Preview CSP Sandbox & Artifact Verification
# ==========================================

def test_preview_csp_sandboxing():
    with tempfile.TemporaryDirectory() as tmpdir:
        preview = TemplatePreview(tmpdir)
        
        template_data = {
            "components": [
                {"id": "c1", "tag": "div", "content": "Preview Item"}
            ]
        }
        
        html_out = preview.render_preview(template_data)
        
        # Assert browser-level CSP sandbox is present
        assert "Content-Security-Policy" in html_out
        assert "sandbox" in html_out
        assert "default-src 'none'" in html_out


def test_wire_artifact_cryptographic_checksum():
    with tempfile.TemporaryDirectory() as tmpdir:
        source_dir = os.path.join(tmpdir, "source")
        output_file = os.path.join(tmpdir, "package.wire")
        extract_dir = os.path.join(tmpdir, "extracted")
        
        os.makedirs(source_dir)
        with open(os.path.join(source_dir, "file1.txt"), "w") as f:
            f.write("Hello World")
        os.makedirs(os.path.join(source_dir, "assets"))
        with open(os.path.join(source_dir, "assets", "style.css"), "w") as f:
            f.write("body { color: red; }")
            
        # 1. Package
        WireArtifact.package(source_dir, output_file, {"name": "test"})
        assert os.path.exists(output_file)
        
        # 2. Verify clean package
        res = WireArtifact.verify(output_file)
        assert res["valid"] is True
        assert res["files_checked"] == 2
        
        # 3. Extract and check contents
        WireArtifact.extract(output_file, extract_dir)
        assert os.path.exists(os.path.join(extract_dir, "file1.txt"))
        assert os.path.exists(os.path.join(extract_dir, "assets", "style.css"))
        
        # 4. Tamper package: modify a file inside and re-verify
        import zipfile
        tampered_file = os.path.join(tmpdir, "tampered.wire")
        
        with zipfile.ZipFile(output_file, "r") as z_in:
            with zipfile.ZipFile(tampered_file, "w") as z_out:
                for item in z_in.infolist():
                    data = z_in.read(item.filename)
                    if item.filename == "file1.txt":
                        # Modify the content of file1.txt to trigger checksum error
                        data = b"Hello Tampered World"
                    z_out.writestr(item, data)
                    
        tampered_res = WireArtifact.verify(tampered_file)
        assert tampered_res["valid"] is False
        assert any("Checksum mismatch" in err for err in tampered_res["errors"])
