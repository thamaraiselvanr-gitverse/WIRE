from typing import Any, Dict, List

import structlog
from playwright.async_api import Page

logger = structlog.get_logger(__name__)


class ShadowPiercer:
    """
    Extracts content from Shadow DOM and Web Components.
    Recursively pierces shadow roots to access encapsulated content.
    """

    async def extract_shadow_content(self, page: Page) -> List[Dict[str, Any]]:
        logger.info("piercing_shadow_dom")

        shadow_content = await page.evaluate("""
            () => {
                const results = [];
                const allowedProps = [
                    'color', 'background-color', 'background', 'font-family', 'font-size', 'font-weight', 'line-height',
                    'padding', 'padding-top', 'padding-bottom', 'padding-left', 'padding-right',
                    'margin', 'margin-top', 'margin-bottom', 'margin-left', 'margin-right',
                    'display', 'flex-direction', 'justify-content', 'align-items',
                    'position', 'top', 'bottom', 'left', 'right', 'width', 'height', 'max-width', 'border', 'border-radius'
                ];

                function getPath(node) {
                    if (!node) return "";
                    if (node.id) return '#' + CSS.escape(node.id);
                    let path = [];
                    while (node && node !== document.documentElement) {
                        if (node.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
                            break;
                        }
                        let name = node.nodeName.toLowerCase();
                        let sib = node, nth = 1;
                        while (sib = sib.previousElementSibling) {
                            if (sib.nodeName.toLowerCase() == name) nth++;
                        }
                        path.unshift(name + ":nth-of-type(" + nth + ")");
                        node = node.parentNode;
                    }
                    return path.join(" > ");
                }

                function calculateSpecificity(selector) {
                    let ids = 0, classes = 0, tags = 0;
                    if (!selector) return [0, 0, 0];
                    const idMatches = selector.match(/#[a-zA-Z0-9_-]+/g);
                    if (idMatches) ids = idMatches.length;
                    const classMatches = selector.match(/\\.[a-zA-Z0-9_-]+/g);
                    if (classMatches) classes += classMatches.length;
                    const attrMatches = selector.match(/\\[[^\\]]+\\]/g);
                    if (attrMatches) classes += attrMatches.length;
                    const pseudoMatches = selector.match(/:[a-zA-Z0-9_-]+/g);
                    if (pseudoMatches) classes += pseudoMatches.length;
                    
                    const tagMatches = selector.match(/(^|[^a-zA-Z0-9_-])[a-zA-Z0-9_-]+/g);
                    if (tagMatches) {
                        tagMatches.forEach(t => {
                            const clean = t.replace(/[^a-zA-Z0-9_-]/g, "");
                            if (clean && clean !== "not" && clean !== "hover" && clean !== "active") {
                                tags++;
                            }
                        });
                    }
                    return [ids, classes, tags];
                }

                function serializeShadowRoot(shadowRoot) {
                    // Extract styles
                    const sheets = [];
                    if (shadowRoot.styleSheets) {
                        Array.from(shadowRoot.styleSheets).forEach(s => {
                            try { sheets.push(s); } catch(e) {}
                        });
                    }
                    if (shadowRoot.adoptedStyleSheets) {
                        Array.from(shadowRoot.adoptedStyleSheets).forEach(s => {
                            sheets.push(s);
                        });
                    }

                    const rules = [];
                    let ruleIndex = 0;
                    sheets.forEach(sheet => {
                        try {
                            const cssRules = sheet.cssRules || sheet.rules;
                            if (cssRules) {
                                Array.from(cssRules).forEach(rule => {
                                    if (rule.type === CSSRule.STYLE_RULE) {
                                        const spec = calculateSpecificity(rule.selectorText);
                                        rules.push({
                                            selector: rule.selectorText,
                                            style: rule.style,
                                            specificity: spec,
                                            index: ruleIndex++
                                        });
                                    }
                                });
                            }
                        } catch(e) {}
                    });

                    const provenance = rules.length > 0 ? "cascade_resolved" : "computed_fallback";

                    function serializeNode(node) {
                        if (node.nodeType === Node.TEXT_NODE) {
                            const text = node.textContent.trim();
                            if (text) {
                                return {
                                    tag: "#text",
                                    text_content: text
                                };
                            }
                            return null;
                        }
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            const tag = node.tagName.toLowerCase();
                            if (["script", "style", "meta", "noscript", "link", "title", "head"].includes(tag)) {
                                return null;
                            }

                            const attributes = {};
                            for (let i = 0; i < node.attributes.length; i++) {
                                attributes[node.attributes[i].name] = node.attributes[i].value;
                            }

                            const styles = {};
                            if (provenance === "cascade_resolved") {
                                // Scoped cascade resolution within this shadow root
                                const matchingRules = [];
                                rules.forEach(r => {
                                    try {
                                        if (node.matches(r.selector)) {
                                            matchingRules.push(r);
                                        }
                                    } catch(e) {}
                                });

                                // Sort rules: specificity asc, source order asc
                                matchingRules.sort((a, b) => {
                                    if (a.specificity[0] !== b.specificity[0]) return a.specificity[0] - b.specificity[0];
                                    if (a.specificity[1] !== b.specificity[1]) return a.specificity[1] - b.specificity[1];
                                    if (a.specificity[2] !== b.specificity[2]) return a.specificity[2] - b.specificity[2];
                                    return a.index - b.index;
                                });

                                // Merge matching styles
                                allowedProps.forEach(prop => {
                                    matchingRules.forEach(r => {
                                        const val = r.style.getPropertyValue(prop) || r.style[prop];
                                        if (val) styles[prop] = val;
                                    });
                                    // Override with inline style if present
                                    const inlineVal = node.style.getPropertyValue(prop) || node.style[prop];
                                    if (inlineVal) styles[prop] = inlineVal;
                                });
                            } else {
                                // Computed styles fallback
                                const computed = getComputedStyle(node);
                                allowedProps.forEach(prop => {
                                    const val = computed.getPropertyValue(prop) || computed[prop];
                                    if (val) styles[prop] = val;
                                });
                            }

                            const children = [];
                            node.childNodes.forEach(child => {
                                const sChild = serializeNode(child);
                                if (sChild) children.push(sChild);
                            });

                            // Nested shadow root inside this element
                            let nestedShadow = null;
                            const nestedSr = node.shadowRoot || node.__wire_shadow_root_ref__;
                            if (nestedSr) {
                                nestedShadow = serializeShadowRoot(nestedSr);
                            }

                            return {
                                tag: tag,
                                attributes: attributes,
                                styles: styles,
                                children: children,
                                shadow_root: nestedShadow,
                                style_provenance: provenance
                            };
                        }
                        return null;
                    }

                    // Root of the shadow DOM is serialized as a div-like container or a virtual shadow-root
                    const children = [];
                    shadowRoot.childNodes.forEach(child => {
                        const sChild = serializeNode(child);
                        if (sChild) children.push(sChild);
                    });

                    return {
                        tag: "#shadow-root",
                        children: children,
                        style_provenance: provenance
                    };
                }

                function walkShadow(root) {
                    const els = root.querySelectorAll('*');
                    els.forEach(el => {
                        const sr = el.shadowRoot || el.__wire_shadow_root_ref__;
                        if (sr) {
                            const shadowTree = serializeShadowRoot(sr);
                            results.push({
                                host_path: getPath(el),
                                shadow_tree: shadowTree
                            });
                            walkShadow(sr);
                        }
                    });
                }

                walkShadow(document);
                return results;
            }
        """)

        logger.info(
            "shadow_dom_extraction_complete", components_found=len(shadow_content)
        )
        return shadow_content  # type: ignore[no-any-return]
