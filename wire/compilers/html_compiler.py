from wire.schema.canonical import CanonicalDesignSchema, ComponentNode
from wire.compilers.sanitizer import HtmlSanitizer
import structlog

logger = structlog.get_logger(__name__)

class HTMLCompiler:
    def compile(self, cids: CanonicalDesignSchema, injected_data: dict = None) -> str:
        logger.info("compiling_cids_to_html", url=cids.url)
        injected_data = injected_data or {}
        
        def render_node(node: ComponentNode) -> str:
            # Unsafe tags filtering (defense-in-depth)
            if node.tag in HtmlSanitizer.UNSAFE_TAGS and node.tag != "#shadow-root":
                return ""

            if node.slot_id and node.slot_id in injected_data:
                content = str(injected_data[node.slot_id])
            else:
                content = node.text_content or ""
                
            children_str = "".join([render_node(c) for c in node.children])
            
            # Integrate Shadow DOM as Declarative Shadow DOM template
            if node.shadow_root:
                # Use open mode so the template remains inspectable in preview/verification
                mode = "open"
                shadow_content = render_node(node.shadow_root)
                children_str = f'<template shadowrootmode="{mode}">{shadow_content}</template>' + children_str
            
            # Sanitize attributes (defense-in-depth)
            attrs_parts = []
            for k, v in node.attributes.items():
                if k.lower().startswith("on"):
                    continue
                if k.lower() in {"href", "src", "action", "formaction"}:
                    if not HtmlSanitizer._is_safe_uri(v):
                        continue
                attrs_parts.append(f'{k}="{v}"')

            attrs = " ".join(attrs_parts)
            if attrs: attrs = " " + attrs
            
            # Sanitize style properties (defense-in-depth)
            style_parts = []
            for k, v in node.styles.items():
                sanitized_val = HtmlSanitizer._sanitize_style_string(v)
                if sanitized_val:
                    style_parts.append(f"{k}: {sanitized_val}")

            styles = "; ".join(style_parts)
            if styles: attrs += f' style="{styles}"'
            
            if node.tag == "#text":
                return content
                
            if node.tag == "#shadow-root":
                return children_str
            
            if not content and not children_str and node.tag in ['img', 'br', 'hr', 'input', 'meta', 'link']:
                return f"<{node.tag}{attrs}/>"
                
            return f"<{node.tag}{attrs}>{content}{children_str}</{node.tag}>"
            
        return render_node(cids.root)
