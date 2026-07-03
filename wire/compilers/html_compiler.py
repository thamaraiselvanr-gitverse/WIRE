import structlog

from wire.compilers.sanitizer import HtmlSanitizer
from wire.compilers.style_emission import render_css
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode

logger = structlog.get_logger(__name__)


class HTMLCompiler:
    def compile(self, cids: CanonicalDesignSchema, injected_data: dict = None) -> str:
        """Compile the CIDS tree to an HTML body fragment prefixed with a
        <style> block for any non-inline (responsive/pseudo/global) rules."""
        body, css = self._compile_parts(cids, injected_data)
        style_block = f"<style>\n{css}\n</style>" if css else ""
        return style_block + body

    def compile_document(
        self,
        cids: CanonicalDesignSchema,
        injected_data: dict = None,
        title: str = None,
    ) -> str:
        """Compile the CIDS tree to a complete, standalone HTML5 document with a
        proper <head> carrying the generated stylesheet (webfonts, animations,
        breakpoints, interaction states) so the editable reconstruction opens
        faithfully on its own."""
        body, css = self._compile_parts(cids, injected_data, unwrap_root=True)
        doc_title = title or cids.url or "WIRE reconstruction"
        head_parts = [
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{doc_title}</title>",
        ]
        if css:
            head_parts.append(f"<style>\n{css}\n</style>")
        head = "\n".join(head_parts)
        return (
            "<!doctype html>\n"
            '<html lang="en">\n'
            f"<head>\n{head}\n</head>\n"
            f"<body>\n{body}\n</body>\n"
            "</html>\n"
        )

    def _compile_parts(
        self,
        cids: CanonicalDesignSchema,
        injected_data: dict = None,
        unwrap_root: bool = False,
    ) -> tuple[str, str]:
        """Render the body HTML and the generated CSS text (no <style> tag).

        When ``unwrap_root`` is set and the CIDS root is an ``<html>``/``<body>``
        wrapper, its inner content is rendered directly so a document build does
        not nest a second ``<body>`` inside its own.
        """
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

        if unwrap_root and cids.root.tag in ("html", "body"):
            target = cids.root
            if target.tag == "html":
                target = next((c for c in target.children if c.tag == "body"), target)
            body = "".join(render_node(c) for c in target.children)
        else:
            body = render_node(cids.root)

        css = render_css(
            getattr(cids, "global_styles", []), pseudo_rules, responsive_rules
        )
        return body, css
