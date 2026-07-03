from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any


class DesignTokens(BaseModel):
    colors: Dict[str, str] = Field(default_factory=dict)
    typography: Dict[str, str] = Field(default_factory=dict)
    spacing: Dict[str, str] = Field(default_factory=dict)


class ComponentNode(BaseModel):
    tag: str
    attributes: Dict[str, str] = Field(default_factory=dict)
    styles: Dict[str, str] = Field(default_factory=dict)
    # Breakpoint-scoped styles: { "@media (max-width: 768px)": { prop: value } }.
    # Inline styles cannot express media queries, so these are compiled into a
    # generated <style> block rather than flattened onto the element.
    responsive_styles: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    # Interaction-state styles from CSS: { ":hover": { prop: value }, ... }.
    # Like media queries, these can only be expressed via a scoped <style> rule.
    pseudo_styles: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    interactions: Dict[str, Any] = Field(default_factory=dict)
    text_content: Optional[str] = None
    children: List["ComponentNode"] = Field(default_factory=list)
    slot_id: Optional[str] = None
    shadow_root: Optional["ComponentNode"] = None
    style_provenance: Optional[str] = None
    layout_role: Optional[str] = None
    removable: bool = True


ComponentNode.model_rebuild()


class CanonicalDesignSchema(BaseModel):
    url: str
    viewport: str = "desktop"
    tokens: DesignTokens = Field(default_factory=DesignTokens)
    root: ComponentNode


from bs4 import BeautifulSoup, NavigableString, Comment
from wire.compilers.sanitizer import HtmlSanitizer


class HTMLToCidsParser:
    INHERITABLE_PROPS = {
        "color",
        "font-family",
        "font-size",
        "font-weight",
        "line-height",
        "text-align",
        "visibility",
        "cursor",
        "white-space",
        "word-break",
    }

    @staticmethod
    def _resolve_vars(val: str, scope: dict) -> str:
        if "var(" not in val:
            return val

        import re

        def replace_var(match):
            inner = match.group(1).split(",")
            var_name = inner[0].strip()
            fallback = inner[1].strip() if len(inner) > 1 else ""
            return scope.get(var_name, fallback)

        max_iters = 5
        for _ in range(max_iters):
            if "var(" not in val:
                break
            val = re.sub(r"var\(([^)]+)\)", replace_var, val)
        return val

    @staticmethod
    def parse(
        soup_or_html,
        style_map: dict = None,
        interactions_map: dict = None,
        shadow_roots_map: dict = None,
        responsive_map: dict = None,
        pseudo_map: dict = None,
    ) -> ComponentNode:
        if isinstance(soup_or_html, str):
            soup = BeautifulSoup(soup_or_html, "lxml")
        else:
            soup = soup_or_html

        style_map = style_map or {}
        interactions_map = interactions_map or {}
        shadow_roots_map = shadow_roots_map or {}
        responsive_map = responsive_map or {}
        pseudo_map = pseudo_map or {}
        # Prefer the body tag, otherwise root html, otherwise the whole document
        root_element = getattr(soup, "body", None)
        if not root_element:
            root_element = soup.find("html") if hasattr(soup, "find") else soup

        return HTMLToCidsParser._process_node(
            root_element,
            style_map,
            None,
            interactions_map,
            shadow_roots_map,
            responsive_map,
            pseudo_map,
        ) or ComponentNode(tag="div")

    @staticmethod
    def _process_node(
        node,
        style_map: dict,
        inherited_styles: dict = None,
        interactions_map: dict = None,
        shadow_roots_map: dict = None,
        responsive_map: dict = None,
        pseudo_map: dict = None,
    ) -> Optional[ComponentNode]:
        if isinstance(node, Comment):
            return None
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                return ComponentNode(tag="#text", text_content=text)
            return None

        # Exclude non-visual tags and unsafe tags from the CIDS tree
        if node.name in [
            "script",
            "style",
            "meta",
            "noscript",
            "link",
            "title",
            "head",
            "iframe",
            "object",
            "embed",
            "applet",
        ]:
            return None

        attributes = {}
        if hasattr(node, "attrs"):
            for k, v in node.attrs.items():
                # Strip inline event handlers
                if k.lower().startswith("on"):
                    continue
                # Strip unsafe URI protocols
                if k.lower() in {"href", "src", "action", "formaction"}:
                    val_str = " ".join(v) if isinstance(v, list) else str(v)
                    if not HtmlSanitizer._is_safe_uri(val_str):
                        continue

                if isinstance(v, list):
                    attributes[k] = " ".join(v)
                else:
                    attributes[k] = str(v)

        inherited_styles = inherited_styles or {}
        explicit_styles = style_map.get(id(node), {})

        effective_scope = inherited_styles.copy()
        effective_scope.update(explicit_styles)

        styles_for_node = {}
        for k, v in effective_scope.items():
            if k in explicit_styles or k in HTMLToCidsParser.INHERITABLE_PROPS:
                resolved_val = HTMLToCidsParser._resolve_vars(v, effective_scope)
                # Sanitize CSS expression and javascript: URL injections
                sanitized_val = HtmlSanitizer._sanitize_style_string(resolved_val)
                if sanitized_val:
                    styles_for_node[k] = sanitized_val

        next_inheritance = {}
        for k, v in effective_scope.items():
            if k in HTMLToCidsParser.INHERITABLE_PROPS or k.startswith("--"):
                next_inheritance[k] = HTMLToCidsParser._resolve_vars(v, effective_scope)

        interactions_map = interactions_map or {}
        interactions = interactions_map.get(id(node), {})

        # Responsive (@media) styles, filtered to the same allowed property set
        # already applied to base styles via the sanitizer.
        responsive_map = responsive_map or {}
        responsive_styles = {}
        for media_query, props in responsive_map.get(id(node), {}).items():
            sanitized_props = {}
            for k, v in props.items():
                resolved_val = HTMLToCidsParser._resolve_vars(v, effective_scope)
                sanitized_val = HtmlSanitizer._sanitize_style_string(resolved_val)
                if sanitized_val:
                    sanitized_props[k] = sanitized_val
            if sanitized_props:
                responsive_styles[media_query] = sanitized_props

        # Interaction-state (:hover/:focus/:active) styles from CSS.
        pseudo_map = pseudo_map or {}
        pseudo_styles = {}
        for pseudo, props in pseudo_map.get(id(node), {}).items():
            sanitized_props = {}
            for k, v in props.items():
                resolved_val = HTMLToCidsParser._resolve_vars(v, effective_scope)
                sanitized_val = HtmlSanitizer._sanitize_style_string(resolved_val)
                if sanitized_val:
                    sanitized_props[k] = sanitized_val
            if sanitized_props:
                pseudo_styles[pseudo] = sanitized_props

        # Compute selector path to look up shadow DOMs
        shadow_roots_map = shadow_roots_map or {}

        # Helper to generate unique path matching Playwright
        def get_path(n):
            if not n:
                return ""
            if n.get("id"):
                return f"#{n.get('id')}"
            path = []
            curr = n
            while curr and curr.name != "[document]":
                if curr.name == "html":
                    break
                name = curr.name
                siblings = curr.find_previous_siblings(name)
                nth = len(siblings) + 1
                path.insert(0, f"{name}:nth-of-type({nth})")
                curr = curr.parent
            return " > ".join(path)

        path = get_path(node)
        shadow_root = shadow_roots_map.get(path)

        children = []
        if hasattr(node, "children"):
            for child in node.children:
                child_node = HTMLToCidsParser._process_node(
                    child,
                    style_map,
                    next_inheritance,
                    interactions_map,
                    shadow_roots_map,
                    responsive_map,
                    pseudo_map,
                )
                if child_node:
                    children.append(child_node)

        return ComponentNode(
            tag=node.name or "div",
            attributes=attributes,
            styles=styles_for_node,
            responsive_styles=responsive_styles,
            pseudo_styles=pseudo_styles,
            interactions=interactions,
            children=children,
            shadow_root=shadow_root,
        )
