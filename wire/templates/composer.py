import re
from typing import Any, Dict, List, Set

import structlog

logger = structlog.get_logger(__name__)


class TemplateComposer:
    """Component-level composition with identity tracking.

    Merges components sourced from different templates into one deterministic
    set, namespacing colliding ids and flagging structurally invalid HTML
    nesting (e.g. a block-level element inside an inline element).
    """

    INLINE_TAGS = {
        "span",
        "a",
        "b",
        "i",
        "em",
        "strong",
        "small",
        "label",
        "code",
        "abbr",
        "cite",
        "s",
        "sub",
        "sup",
        "mark",
    }
    BLOCK_TAGS = {
        "div",
        "p",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "nav",
        "ul",
        "ol",
        "li",
        "table",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }

    def compose(self, components: List[Dict[str, Any]]) -> Dict[str, Any]:
        seen_ids: Set[Any] = set()
        composed: List[Dict[str, Any]] = []
        errors: List[str] = []

        for index, component in enumerate(components):
            comp = dict(component)
            comp_id = comp.get("id", f"component_{index}")

            # 1. Collision resolution — namespace duplicates by source template.
            if comp_id in seen_ids:
                source = comp.get("source_template")
                new_id = f"{source}_{comp_id}" if source else f"{comp_id}_{index}"
                logger.info("component_id_collision", original=comp_id, resolved=new_id)
                comp_id = new_id
            comp["id"] = comp_id
            seen_ids.add(comp_id)

            # 2. Structural nesting validation.
            tag = (comp.get("tag") or "").lower()
            content = comp.get("content") or ""
            if tag in self.INLINE_TAGS:
                nested_block = self._first_block_tag(content)
                if nested_block:
                    errors.append(
                        f"Invalid HTML nesting: <{nested_block}> inside <{tag}> "
                        f"(component '{comp_id}')"
                    )

            composed.append(comp)

        return {
            "component_count": len(components),
            "components": composed,
            "errors": errors,
        }

    def _first_block_tag(self, content: str) -> str:
        for match in re.findall(r"<\s*([a-zA-Z0-9]+)", content):
            if match.lower() in self.BLOCK_TAGS:
                return match.lower()  # type: ignore[no-any-return]
        return ""
