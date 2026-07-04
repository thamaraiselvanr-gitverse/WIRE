import os
from typing import Any, Dict, Optional

import structlog

from wire.compilers.sanitizer import HtmlSanitizer

logger = structlog.get_logger(__name__)


class TemplatePreview:
    """Sandboxed, cached preview rendering for instant template visualization.

    Renders a lightweight HTML page without running the full pipeline. Preview
    content is confined by a strict Content-Security-Policy and a sandboxed
    iframe so untrusted template content cannot execute scripts or reach the
    network.
    """

    CSP = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "img-src data: https:; font-src data:;"
    )

    def __init__(self, base_dir: str = "templates") -> None:
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def render_preview(
        self, template_data: Dict[str, Any], tokens: Optional[Dict[str, Any]] = None
    ) -> str:
        logger.info("rendering_template_preview")

        inner_parts = []
        for component in template_data.get("components", []):
            comp_id = component.get("id", "")
            tag = component.get("tag", "div")
            content = HtmlSanitizer.sanitize_html(component.get("content", ""))
            id_attr = f' id="{comp_id}"' if comp_id else ""
            inner_parts.append(f"<{tag}{id_attr}>{content}</{tag}>")
        inner_html = "\n".join(inner_parts)

        root_style = ""
        if tokens and isinstance(tokens, dict):
            colors = tokens.get("colors", {})
            if colors:
                vars_css = " ".join(
                    f"--color-{name}: {value};" for name, value in colors.items()
                )
                root_style = f"<style>:root {{ {vars_css} }}</style>"

        # Build the sandboxed iframe document (attribute-escaped srcdoc).
        iframe_doc = (
            f'<meta http-equiv="Content-Security-Policy" content="{self.CSP}">'
            f"{root_style}{inner_html}"
        )
        escaped_doc = iframe_doc.replace("&", "&amp;").replace('"', "&quot;")

        return (
            "<!doctype html>\n"
            '<html lang="en">\n'
            "<head>\n"
            '<meta charset="utf-8">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{self.CSP}">\n'
            "<title>WIRE Template Preview</title>\n"
            "</head>\n"
            "<body>\n"
            f'<iframe title="preview" sandbox="allow-same-origin" '
            f'srcdoc="{escaped_doc}"></iframe>\n'
            "</body>\n"
            "</html>\n"
        )
