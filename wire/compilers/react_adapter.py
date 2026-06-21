import structlog
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode
from wire.compilers.sanitizer import HtmlSanitizer

logger = structlog.get_logger(__name__)


class ReactAdapter:
    """
    CIDS → React component compiler.
    Independent adapter consuming the Canonical Intermediate Design Schema.

    NOTE ON SHADOW DOM COMPILATION:
    Shadow DOM content (node.shadow_root) is compiled into browser-native
    Declarative Shadow DOM templates (<template shadowrootmode="open">).
    Because the React virtual DOM reconciler does not natively manage/diff
    subtrees inside declarative shadow roots after mount, all compiled
    shadow root subtrees are STATIC-ONLY. They will render correctly on
    initial mount, but state/props updates to their internal elements
    are not supported by standard React diffing.
    """

    def compile(self, cids: CanonicalDesignSchema) -> str:
        logger.info("compiling_cids_to_react", url=cids.url)

        imports = "import React from 'react';\n\n"
        component = self._render_component(cids.root, "App")

        return imports + component

    def _render_component(self, node: ComponentNode, component_name: str) -> str:
        lines = []
        lines.append(f"function {component_name}() {{")
        lines.append("  return (")
        lines.append(self._render_jsx(node, indent=4))
        lines.append("  );")
        lines.append("}")
        lines.append(f"\nexport default {component_name};")
        return "\n".join(lines)

    def _render_html_string(self, node: ComponentNode) -> str:
        if node.tag == "#text":
            return node.text_content or ""

        # Unsafe tags filtering (defense-in-depth)
        if node.tag in HtmlSanitizer.UNSAFE_TAGS and node.tag != "#shadow-root":
            return ""

        attrs_parts = []
        for key, value in node.attributes.items():
            if key == "style":
                continue
            if key.lower().startswith("on"):
                continue
            if key.lower() in {"href", "src", "action", "formaction"}:
                if not HtmlSanitizer._is_safe_uri(value):
                    continue
            attrs_parts.append(f'{key}="{value}"')

        if node.styles:
            style_parts = []
            for k, v in node.styles.items():
                sanitized_val = HtmlSanitizer._sanitize_style_string(v)
                if sanitized_val:
                    style_parts.append(f"{k}: {sanitized_val}")
            if style_parts:
                style_str = "; ".join(style_parts)
                attrs_parts.append(f'style="{style_str}"')

        attrs_str = (" " + " ".join(attrs_parts)) if attrs_parts else ""

        if not node.children and not node.text_content and not node.shadow_root:
            if node.tag in ['img', 'br', 'hr', 'input', 'meta', 'link']:
                return f"<{node.tag}{attrs_str}/>"
            return f"<{node.tag}{attrs_str}></{node.tag}>"

        content = node.text_content or ""
        children_str = "".join([self._render_html_string(c) for c in node.children])

        if node.shadow_root:
            shadow_html = self._render_html_string(node.shadow_root)
            children_str = f'<template shadowrootmode="open">{shadow_html}</template>' + children_str

        if node.tag == "#shadow-root":
            return children_str

        return f"<{node.tag}{attrs_str}>{content}{children_str}</{node.tag}>"

    def _render_jsx(self, node: ComponentNode, indent: int = 0) -> str:
        prefix = " " * indent
        tag = node.tag

        if tag == "#text":
            return prefix + (node.text_content or "")

        # Unsafe tags filtering (defense-in-depth)
        if tag in HtmlSanitizer.UNSAFE_TAGS and tag != "#shadow-root":
            return ""

        if tag == "#shadow-root":
            html_str = "".join([self._render_html_string(c) for c in node.children])
            # Centralized HTML Sanitization on the generated shadow DOM template string
            sanitized_html = HtmlSanitizer.sanitize_html(html_str)
            escaped_html = sanitized_html.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
            return f'{prefix}<template shadowrootmode="open" dangerouslySetInnerHTML={{{{\n{prefix}  __html: `{escaped_html}`\n{prefix}}}}} />'

        # Build props
        props_parts = []
        for key, value in node.attributes.items():
            if key == "style":
                continue
            if key.lower().startswith("on"):
                continue
            if key.lower() in {"href", "src", "action", "formaction"}:
                if not HtmlSanitizer._is_safe_uri(value):
                    continue
            jsx_key = self._html_attr_to_jsx(key)
            props_parts.append(f'{jsx_key}="{value}"')

        if node.styles:
            style_parts = []
            for k, v in node.styles.items():
                sanitized_val = HtmlSanitizer._sanitize_style_string(v)
                if sanitized_val:
                    style_parts.append(f'"{self._css_to_camel(k)}": "{sanitized_val}"')
            if style_parts:
                style_obj = ", ".join(style_parts)
                props_parts.append(f"style={{{{{style_obj}}}}}")

        props_str = (" " + " ".join(props_parts)) if props_parts else ""

        # Self-closing tags (only if no children, no text, and no shadow_root)
        if not node.children and not node.text_content and not node.shadow_root:
            return f"{prefix}<{tag}{props_str} />"

        content = node.text_content or ""
        children_parts = []
        if node.shadow_root:
            children_parts.append(self._render_jsx(node.shadow_root, indent + 2))
        for c in node.children:
            children_parts.append(self._render_jsx(c, indent + 2))

        children = "\n".join(children_parts)
        inner = content + ("\n" + children if children else "")

        return f"{prefix}<{tag}{props_str}>\n{prefix}  {inner}\n{prefix}</{tag}>"

    @staticmethod
    def _html_attr_to_jsx(attr: str) -> str:
        mapping = {"class": "className", "for": "htmlFor", "tabindex": "tabIndex"}
        return mapping.get(attr, attr)

    @staticmethod
    def _css_to_camel(prop: str) -> str:
        parts = prop.split("-")
        return parts[0] + "".join(p.capitalize() for p in parts[1:])

