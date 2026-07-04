"""Shared generation of the scoped <style> block used by all CIDS compilers.

Inline styles cannot express ``@media`` breakpoints, ``:hover``/``:focus``/
``:active`` interaction states, or document-level ``@font-face``/``@keyframes``
rules. Each compiler therefore assigns a generated class per node that carries
such styles and emits a single stylesheet. This module centralizes that logic so
the HTML, React, and Vue outputs stay consistent.
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from wire.compilers.sanitizer import HtmlSanitizer
from wire.schema.canonical import ComponentNode

_URL_REF_RE = re.compile(r"url\(\s*(['\"]?)([^'\")]+?)\1\s*\)")

# Inline style strings repeated at least this many times across the tree are
# promoted to a shared CSS class instead of being duplicated on every element.
DEDUP_MIN_OCCURRENCES = 2


def sanitized_declarations(node: ComponentNode) -> str:
    """The node's sanitized inline-style declaration string (e.g.
    ``"color: red; padding: 8px"``), or ``""`` if it has none."""
    parts = []
    for k, v in (node.styles or {}).items():
        sanitized_val = HtmlSanitizer._sanitize_style_string(v)
        if sanitized_val:
            parts.append(f"{k}: {sanitized_val}")
    return "; ".join(parts)


def count_inline_styles(
    root: ComponentNode, include_shadow: bool = False
) -> "Counter[str]":
    """Count how often each inline-style string occurs across the tree.

    Mirrors the compilers' skip rules so only styles that actually render are
    eligible for class extraction. ``include_shadow`` follows shadow roots (the
    HTML compiler deduplicates inside declarative shadow DOM; React/Vue render
    shadow content as a static string and leave it inline, so they pass False).
    """
    counter: "Counter[str]" = Counter()

    def walk(node: ComponentNode) -> None:
        if node.tag in HtmlSanitizer.UNSAFE_TAGS and node.tag != "#shadow-root":
            return
        if node.tag not in ("#text", "#shadow-root"):
            style = sanitized_declarations(node)
            if style:
                counter[style] += 1
        if include_shadow and node.shadow_root:
            walk(node.shadow_root)
        for child in node.children:
            walk(child)

    walk(root)
    return counter


def mint_dedup_classes(
    freq: "Counter[str]", min_occurrences: int = DEDUP_MIN_OCCURRENCES
) -> Tuple[Dict[str, str], str]:
    """Turn a style-frequency map into ``(declaration -> class name, css)``.

    Strings occurring at least ``min_occurrences`` times become ``wire-cls-N``
    rules, numbered deterministically by descending frequency then text so the
    output is stable. The CSS is returned so callers can place it ahead of the
    responsive/pseudo rules (letting ``@media`` win at equal specificity).
    """
    shared: Dict[str, str] = {}
    for idx, (style, count) in enumerate(
        sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])), start=1
    ):
        if count >= min_occurrences:
            shared[style] = f"wire-cls-{idx}"
    css = "\n".join(
        f".{cls} {{ {style} }}"
        for style, cls in sorted(shared.items(), key=lambda kv: kv[1])
    )
    return shared, css


def _localize_global_url_refs(rule: str) -> str:
    """Relocate bare same-folder ``url()`` references under ``assets/``.

    The asset downloader rewrites ``url()`` inside an *external* CSS file to a
    bare ``<hash>_name.ext`` (relative to ``assets/``, where that CSS lives).
    But ``@font-face``/``@keyframes`` rules are hoisted verbatim into the
    editable output's ``<style>``, and that document sits at the run root — so a
    bare name resolves to ``<root>/name`` instead of ``<root>/assets/name`` and
    the webfont fails to load. Inline-``<style>`` sources are already
    ``assets/``-prefixed (they contain a ``/``) and are left untouched, as are
    absolute URLs, ``data:`` URIs, and SVG fragment refs. This restores parity
    with the pixel-faithful clone for external-CSS webfonts.
    """

    def repl(match: "re.Match[str]") -> str:
        quote, value = match.group(1), match.group(2)
        v = value.strip()
        if not v or v[0] == "#" or v.startswith("data:") or "/" in v or ":" in v:
            return match.group(0)
        return f"url({quote}assets/{v}{quote})"

    return _URL_REF_RE.sub(repl, rule)


def _sanitize_props(props: Dict[str, Any]) -> Dict[str, Any]:
    safe = {}
    for k, v in (props or {}).items():
        sanitized = HtmlSanitizer._sanitize_style_string(v)
        if sanitized:
            safe[k] = sanitized
    return safe


def safe_global_rules(global_styles: Optional[List[str]]) -> List[str]:
    """Filter document-level at-rules for obvious injection vectors and relocate
    bare ``url()`` references so webfonts resolve from the run-root output."""
    out = []
    for rule in global_styles or []:
        low = rule.lower()
        if any(bad in low for bad in ("javascript:", "expression(", "</", "<script")):
            continue
        out.append(_localize_global_url_refs(rule.strip()))
    return out


def collect_generated_styles(
    root: ComponentNode, global_styles: Optional[List[str]] = None
) -> Tuple[Dict[int, str], str]:
    """Walk the light-DOM tree, assigning a generated class to each node with
    responsive or pseudo styles, and return ``(class_map, css_text)``.

    ``class_map`` maps ``id(node)`` -> generated class name. Shadow subtrees are
    intentionally skipped: a document-level stylesheet cannot pierce shadow
    encapsulation, so scoping generated classes there would be inert.
    """
    class_map: Dict[int, str] = {}
    responsive_rules: Dict[str, list] = {}
    pseudo_rules: List[Any] = []
    counter = [0]

    def walk(node: ComponentNode) -> None:
        media = {}
        for media_query, props in (node.responsive_styles or {}).items():
            safe = _sanitize_props(props)
            if safe:
                media[media_query] = safe

        pseudo = {}
        for state, props in (node.pseudo_styles or {}).items():
            safe = _sanitize_props(props)
            if safe:
                pseudo[state] = safe

        if media or pseudo:
            counter[0] += 1
            cls = f"wire-r{counter[0]}"
            class_map[id(node)] = cls
            for media_query, safe in media.items():
                responsive_rules.setdefault(media_query, []).append((cls, safe))
            for state, safe in pseudo.items():
                pseudo_rules.append((cls, state, safe))

        for child in node.children:
            walk(child)

    walk(root)

    css = render_css(global_styles, pseudo_rules, responsive_rules)
    return class_map, css


def render_css(
    global_styles: Optional[List[str]],
    pseudo_rules: List[Any],
    responsive_rules: Dict[str, Any],
) -> str:
    """Render the final stylesheet text (without the enclosing <style> tag)."""
    blocks: List[str] = []

    for rule in safe_global_rules(global_styles):
        blocks.append(rule)

    for cls, state, props in pseudo_rules:
        decls = "; ".join(f"{k}: {v}" for k, v in props.items())
        blocks.append(f".{cls}{state} {{ {decls} }}")

    for media_query, entries in responsive_rules.items():
        selectors = []
        for cls, props in entries:
            decls = "; ".join(f"{k}: {v}" for k, v in props.items())
            selectors.append(f"  .{cls} {{ {decls} }}")
        blocks.append(f"{media_query} {{\n" + "\n".join(selectors) + "\n}")

    return "\n".join(blocks)


def merge_class(
    existing_class: Optional[str], generated_class: Optional[str]
) -> Optional[str]:
    """Merge a node's existing class attribute with its generated class."""
    if not generated_class:
        return existing_class
    if existing_class:
        return f"{existing_class} {generated_class}"
    return generated_class
