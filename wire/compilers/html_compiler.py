import structlog

from wire.compilers.sanitizer import HtmlSanitizer
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode

logger = structlog.get_logger(__name__)


class HTMLCompiler:
    def compile(self, cids: CanonicalDesignSchema, injected_data: dict = None) -> str:
        logger.info("compiling_cids_to_html", url=cids.url)
        injected_data = injected_data or {}

        # Collected responsive rules: media_query -> [(class_name, {prop: val})].
        # Populated during the render walk, emitted as a single <style> block so
        # breakpoint styling survives (inline styles cannot express @media).
        responsive_rules: dict[str, list] = {}
        self._responsive_counter = 0

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
                children_str = (
                    f'<template shadowrootmode="{mode}">{shadow_content}</template>'
                    + children_str
                )

            # Register responsive styles under a generated class, filtered through
            # the same style sanitizer used for inline styles.
            responsive_class = None
            if node.responsive_styles:
                collected = {}
                for media_query, props in node.responsive_styles.items():
                    safe_props = {}
                    for k, v in props.items():
                        sanitized_val = HtmlSanitizer._sanitize_style_string(v)
                        if sanitized_val:
                            safe_props[k] = sanitized_val
                    if safe_props:
                        collected[media_query] = safe_props
                if collected:
                    self._responsive_counter += 1
                    responsive_class = f"wire-r{self._responsive_counter}"
                    for media_query, safe_props in collected.items():
                        responsive_rules.setdefault(media_query, []).append(
                            (responsive_class, safe_props)
                        )

            # Sanitize attributes (defense-in-depth)
            attrs_parts = []
            merged_class = None
            for k, v in node.attributes.items():
                if k.lower().startswith("on"):
                    continue
                if k.lower() in {"href", "src", "action", "formaction"}:
                    if not HtmlSanitizer._is_safe_uri(v):
                        continue
                if k.lower() == "class" and responsive_class:
                    merged_class = f"{v} {responsive_class}"
                    attrs_parts.append(f'class="{merged_class}"')
                    continue
                attrs_parts.append(f'{k}="{v}"')
            # Add the generated class if the node had no existing class attribute.
            if responsive_class and merged_class is None:
                attrs_parts.append(f'class="{responsive_class}"')

            attrs = " ".join(attrs_parts)
            if attrs:
                attrs = " " + attrs

            # Sanitize style properties (defense-in-depth)
            style_parts = []
            for k, v in node.styles.items():
                sanitized_val = HtmlSanitizer._sanitize_style_string(v)
                if sanitized_val:
                    style_parts.append(f"{k}: {sanitized_val}")

            styles = "; ".join(style_parts)
            if styles:
                attrs += f' style="{styles}"'

            if node.tag == "#text":
                return content

            if node.tag == "#shadow-root":
                return children_str

            if (
                not content
                and not children_str
                and node.tag in ["img", "br", "hr", "input", "meta", "link"]
            ):
                return f"<{node.tag}{attrs}/>"

            return f"<{node.tag}{attrs}>{content}{children_str}</{node.tag}>"

        body = render_node(cids.root)
        style_block = self._render_responsive_style_block(responsive_rules)
        return style_block + body

    @staticmethod
    def _render_responsive_style_block(responsive_rules: dict) -> str:
        """Emit a single <style> element containing all @media rules, or ''."""
        if not responsive_rules:
            return ""
        blocks = []
        for media_query, entries in responsive_rules.items():
            selectors = []
            for class_name, props in entries:
                decls = "; ".join(f"{k}: {v}" for k, v in props.items())
                selectors.append(f"  .{class_name} {{ {decls} }}")
            inner = "\n".join(selectors)
            blocks.append(f"{media_query} {{\n{inner}\n}}")
        return "<style>\n" + "\n".join(blocks) + "\n</style>"
