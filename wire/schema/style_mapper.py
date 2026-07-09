import re
from typing import Any, Dict, List, Tuple

import structlog
import tinycss2
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)


class CascadeResolver:
    def __init__(self) -> None:
        # Reference set of the core visual properties. The gate is now a
        # *denylist* (see ``denied_props`` and ``_accept_prop``): any property
        # is kept unless it is explicitly non-visual/behavioral, so newly-shipped
        # or vendor-prefixed paint properties no longer regress fidelity by being
        # silently dropped. This set is retained for documentation/reference.
        self.allowed_props = {
            "color",
            "background-color",
            "background",
            "background-image",
            "background-size",
            "background-position",
            "background-repeat",
            "font-family",
            "font-size",
            "font-weight",
            "font-style",
            "line-height",
            "letter-spacing",
            "text-align",
            "text-decoration",
            "text-transform",
            "white-space",
            "vertical-align",
            "padding",
            "padding-top",
            "padding-bottom",
            "padding-left",
            "padding-right",
            "margin",
            "margin-top",
            "margin-bottom",
            "margin-left",
            "margin-right",
            "display",
            "flex",
            "flex-direction",
            "flex-wrap",
            "flex-grow",
            "flex-shrink",
            "flex-basis",
            "justify-content",
            "align-items",
            "align-content",
            "align-self",
            "gap",
            "row-gap",
            "column-gap",
            "grid-template-columns",
            "grid-template-rows",
            "grid-template-areas",
            "grid-column",
            "grid-row",
            "grid-area",
            "position",
            "top",
            "bottom",
            "left",
            "right",
            "width",
            "height",
            "min-width",
            "min-height",
            "max-width",
            "max-height",
            "box-sizing",
            "border",
            "border-radius",
            "border-width",
            "border-style",
            "border-color",
            "box-shadow",
            "opacity",
            "overflow",
            "overflow-x",
            "overflow-y",
            "z-index",
            "object-fit",
            "object-position",
            "cursor",
            "list-style",
            "list-style-type",
            "transform",
            "transform-origin",
            "transition",
            "transition-property",
            "transition-duration",
            "transition-timing-function",
            "animation",
            "animation-name",
            "animation-duration",
            "animation-timing-function",
            "animation-iteration-count",
            "animation-delay",
            "animation-fill-mode",
            "filter",
            "backdrop-filter",
            "aspect-ratio",
            "text-shadow",
            "text-overflow",
            "word-break",
            "overflow-wrap",
            "writing-mode",
            "mix-blend-mode",
            "background-blend-mode",
            "background-clip",
            "clip-path",
            "-webkit-clip-path",
            "mask",
            "-webkit-mask-image",
            "outline",
            "outline-offset",
            "inset",
            "place-items",
            "place-content",
            "columns",
            "column-count",
            "visibility",
        }

        # Non-visual / behavioral / reconstruction-hostile properties dropped
        # regardless. Everything else (including custom --* props) is kept.
        self.denied_props = {
            "behavior",
            "-moz-binding",
            "will-change",
            "pointer-events",
            "user-select",
            "-webkit-user-select",
            "-webkit-tap-highlight-color",
            "-webkit-touch-callout",
            "touch-action",
            "scroll-behavior",
            "content",
        }

    def _accept_prop(self, prop: str) -> bool:
        """Keep any property that is not explicitly denied (denylist gate)."""
        return prop.startswith("--") or prop not in self.denied_props

    def _calculate_specificity(
        self, selector: str, source_order: int
    ) -> Tuple[Any, ...]:
        """
        Calculates CSS Specificity tuple: (inline, ids, classes, tags, source_order)
        """
        # Exclude pseudo elements for core mapping
        if ":" in selector:
            selector = re.sub(r":[\w-]+(?:\([^)]*\))?", "", selector)

        ids = selector.count("#")
        classes = selector.count(".") + selector.count("[")

        # Tags are generic words not prefixed by ID/Class triggers
        tags = len(re.findall(r"(?:^|[\s>+~]+)([a-zA-Z0-9]+)", selector))

        return (0, ids, classes, tags, source_order)

    def _valid_decls_from_content(self, content: Any) -> List[Any]:
        """Parse a declaration-list token stream into allowed (prop, value) pairs."""
        decls = tinycss2.parse_declaration_list(
            content, skip_comments=True, skip_whitespace=True
        )
        valid = []
        for decl in decls:
            if getattr(decl, "type", None) == "declaration":
                prop = decl.lower_name
                if self._accept_prop(prop):
                    valid.append((prop, tinycss2.serialize(decl.value).strip()))
        return valid

    def resolve(
        self, html_content: str, css_content: str
    ) -> Tuple[BeautifulSoup, Dict[int, Dict[str, str]]]:
        """
        Performs the heavy mapping of CSS definitions onto HTML targets.
        Yields a modified parsed HTML and an element style map.
        id(bs4_element) -> { property -> value }

        Responsive (``@media``) rules are captured separately into
        ``self.responsive_map`` (id(bs4_element) -> { media_query -> {prop: val} })
        so breakpoint-specific styling is preserved rather than dropped.
        """
        logger.info("resolving_css_cascade_started")
        soup = BeautifulSoup(html_content, "lxml")

        # id(element) -> { "@media ...": { prop: value } }
        self.responsive_map: Dict[int, Dict[str, Dict[str, str]]] = {}
        # id(element) -> { ":hover": { prop: value }, ":focus": {...}, ":active": {...} }
        self.pseudo_map: Dict[int, Dict[str, Dict[str, str]]] = {}
        # Document-level at-rules (@font-face, @keyframes) captured verbatim.
        self.global_styles: List[Any] = []

        # Collect internal style tags into global css execution run
        for style_tag in soup.find_all("style"):
            if style_tag.string:
                css_content += "\n" + style_tag.string

        rules = tinycss2.parse_stylesheet(
            css_content, skip_comments=True, skip_whitespace=True
        )

        element_styles_map = {}
        element_specificity_map: Dict[int, Dict[str, Any]] = {}

        rule_count = 0
        mapped_elements = set()

        for rule in rules:
            if getattr(rule, "type", None) == "qualified-rule":
                selector = tinycss2.serialize(rule.prelude).strip()
                decls = tinycss2.parse_declaration_list(
                    rule.content, skip_comments=True, skip_whitespace=True
                )

                # Fast track declarations matching allowed properties
                valid_decls = []
                for decl in decls:
                    if getattr(decl, "type", None) == "declaration":
                        prop = decl.lower_name
                        if self._accept_prop(prop):
                            valid_decls.append(
                                (prop, tinycss2.serialize(decl.value).strip())
                            )

                if not valid_decls:
                    continue

                rule_count += 1
                for sub_sel in selector.split(","):
                    sub_sel = sub_sel.strip()
                    if not sub_sel:
                        continue

                    # Pseudo-elements and low-value dynamic states cannot be
                    # reconstructed cleanly as a scoped style rule — skip them.
                    if any(
                        t in sub_sel
                        for t in ("::before", "::after", ":visited", ":focus-within")
                    ):
                        continue

                    # Capture :hover/:focus/:active into the pseudo map keyed by
                    # the base element (pseudo stripped), for emission as scoped
                    # rules — inline styles cannot express interaction states.
                    captured_pseudo = next(
                        (p for p in (":hover", ":focus", ":active") if p in sub_sel),
                        None,
                    )
                    if captured_pseudo:
                        base_sel = re.sub(
                            r"::?[\w-]+(?:\([^)]*\))?", "", sub_sel
                        ).strip()
                        if not base_sel:
                            continue
                        try:
                            pseudo_matches = soup.select(base_sel)
                        except Exception:
                            continue
                        for el in pseudo_matches:
                            el_id = id(el)
                            mapped_elements.add(el_id)
                            bucket = self.pseudo_map.setdefault(el_id, {}).setdefault(
                                captured_pseudo, {}
                            )
                            for prop, val in valid_decls:
                                bucket[prop] = val
                        continue

                    try:
                        matches = soup.select(sub_sel)
                        if not matches:
                            continue
                        spec = self._calculate_specificity(sub_sel, rule_count)
                    except Exception:
                        continue

                    for el in matches:
                        el_id = id(el)
                        mapped_elements.add(el_id)
                        if el_id not in element_specificity_map:
                            element_specificity_map[el_id] = {}

                        for prop, val in valid_decls:
                            # Evaluate Spec: Inline > IDs > Classes > Tags > SourceOrder
                            current_spec = element_specificity_map[el_id].get(
                                prop, ((-1, -1, -1, -1, -1), "")
                            )[0]
                            if spec >= current_spec:
                                element_specificity_map[el_id][prop] = (spec, val)

            elif (
                getattr(rule, "type", None) == "at-rule"
                and getattr(rule, "lower_at_keyword", None) == "media"
                and rule.content is not None
            ):
                media_query = "@media " + tinycss2.serialize(rule.prelude).strip()
                inner_rules = tinycss2.parse_rule_list(
                    rule.content, skip_comments=True, skip_whitespace=True
                )
                for inner in inner_rules:
                    if getattr(inner, "type", None) != "qualified-rule":
                        continue
                    inner_sel = tinycss2.serialize(inner.prelude).strip()
                    inner_decls = self._valid_decls_from_content(inner.content)
                    if not inner_decls:
                        continue
                    for sub_sel in inner_sel.split(","):
                        sub_sel = sub_sel.strip()
                        if not sub_sel or "::" in sub_sel:
                            continue
                        try:
                            matches = soup.select(sub_sel)
                        except Exception:
                            continue
                        for el in matches:
                            el_id = id(el)
                            mapped_elements.add(el_id)
                            bucket = self.responsive_map.setdefault(
                                el_id, {}
                            ).setdefault(media_query, {})
                            # Source-order last-wins within a media block.
                            for prop, val in inner_decls:
                                bucket[prop] = val

            elif getattr(rule, "type", None) == "at-rule" and getattr(
                rule, "lower_at_keyword", None
            ) in ("font-face", "keyframes", "-webkit-keyframes", "-moz-keyframes"):
                # Document-level rules (webfonts, animations) captured verbatim;
                # they are not element-scoped so they can't be flattened inline.
                try:
                    self.global_styles.append(rule.serialize().strip())
                except Exception:
                    pass

        # Evaluate Inline Styles Overrides
        for el in soup.find_all(style=True):
            el_id = id(el)
            mapped_elements.add(el_id)
            if el_id not in element_specificity_map:
                element_specificity_map[el_id] = {}

            inline_css = el["style"]
            inline_decls = tinycss2.parse_declaration_list(
                inline_css, skip_comments=True, skip_whitespace=True
            )
            for decl in inline_decls:
                if getattr(decl, "type", None) == "declaration":
                    prop = decl.lower_name
                    if self._accept_prop(prop):
                        val = tinycss2.serialize(decl.value).strip()
                        element_specificity_map[el_id][prop] = ((1, 0, 0, 0, 0), val)

        # Condense specificity map down into final literal dict
        for el_id, props in element_specificity_map.items():
            element_styles_map[el_id] = {p: props[p][1] for p in props}

        logger.info(
            "resolving_css_cascade_finished",
            rules_evaluated=rule_count,
            elements_styled=len(mapped_elements),
        )

        return soup, element_styles_map
