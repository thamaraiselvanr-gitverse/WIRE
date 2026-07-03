import structlog

from wire.compilers.sanitizer import HtmlSanitizer
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode

logger = structlog.get_logger(__name__)


class HTMLCompiler:
    def compile(self, cids: CanonicalDesignSchema, injected_data: dict = None) -> str:
        logger.info("compiling_cids_to_html", url=cids.url)
        injected_data = injected_data or {}

        # Rules that inline styles cannot express, emitted as one <style> block:
        #   responsive_rules: media_query -> [(class_name, {prop: val})]
        #   pseudo_rules:     [(class_name, pseudo, {prop: val})]
        # A single generated class per node carries both.
        responsive_rules: dict[str, list] = {}
        pseudo_rules: list = []
        self._gen_class_counter = 0

        def _sanitize_props(props: dict) -> dict:
            safe = {}
            for k, v in props.items():
                sanitized_val = HtmlSanitizer._sanitize_style_string(v)
                if sanitized_val:
                    safe[k] = sanitized_val
            return safe

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

            # Collect responsive + pseudo styles (which inline styles can't
            # express) under a single generated class, sanitized like inline.
            collected_media = {}
            for media_query, props in (node.responsive_styles or {}).items():
                safe_props = _sanitize_props(props)
                if safe_props:
                    collected_media[media_query] = safe_props

            collected_pseudo = {}
            for pseudo, props in (node.pseudo_styles or {}).items():
                safe_props = _sanitize_props(props)
                if safe_props:
                    collected_pseudo[pseudo] = safe_props

            gen_class = None
            if collected_media or collected_pseudo:
                self._gen_class_counter += 1
                gen_class = f"wire-r{self._gen_class_counter}"
                for media_query, safe_props in collected_media.items():
                    responsive_rules.setdefault(media_query, []).append(
                        (gen_class, safe_props)
                    )
                for pseudo, safe_props in collected_pseudo.items():
                    pseudo_rules.append((gen_class, pseudo, safe_props))

            # Sanitize attributes (defense-in-depth)
            attrs_parts = []
            merged_class = None
            for k, v in node.attributes.items():
                if k.lower().startswith("on"):
                    continue
                if k.lower() in {"href", "src", "action", "formaction"}:
                    if not HtmlSanitizer._is_safe_uri(v):
                        continue
                if k.lower() == "class" and gen_class:
                    merged_class = f"{v} {gen_class}"
                    attrs_parts.append(f'class="{merged_class}"')
                    continue
                attrs_parts.append(f'{k}="{v}"')
            # Add the generated class if the node had no existing class attribute.
            if gen_class and merged_class is None:
                attrs_parts.append(f'class="{gen_class}"')

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
        style_block = self._render_style_block(responsive_rules, pseudo_rules)
        return style_block + body

    @staticmethod
    def _render_style_block(responsive_rules: dict, pseudo_rules: list) -> str:
        """Emit one <style> element with all @media and pseudo rules, or ''."""
        if not responsive_rules and not pseudo_rules:
            return ""
        blocks = []

        # Pseudo-class (:hover/:focus/:active) rules.
        for class_name, pseudo, props in pseudo_rules:
            decls = "; ".join(f"{k}: {v}" for k, v in props.items())
            blocks.append(f".{class_name}{pseudo} {{ {decls} }}")

        # Responsive (@media) rules.
        for media_query, entries in responsive_rules.items():
            selectors = []
            for class_name, props in entries:
                decls = "; ".join(f"{k}: {v}" for k, v in props.items())
                selectors.append(f"  .{class_name} {{ {decls} }}")
            inner = "\n".join(selectors)
            blocks.append(f"{media_query} {{\n{inner}\n}}")

        return "<style>\n" + "\n".join(blocks) + "\n</style>"
