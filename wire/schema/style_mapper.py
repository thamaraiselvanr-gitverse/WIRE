import structlog
import tinycss2
import re
from bs4 import BeautifulSoup
from typing import Dict, Tuple, Any

logger = structlog.get_logger(__name__)

class CascadeResolver:
    def __init__(self):
        # We explicitly limit scope to core visual properties to ensure precision 
        # before expanding coverage to interactive layouts.
        self.allowed_props = {
            'color', 'background-color', 'background', 'font-family', 'font-size', 'font-weight', 'line-height',
            'padding', 'padding-top', 'padding-bottom', 'padding-left', 'padding-right',
            'margin', 'margin-top', 'margin-bottom', 'margin-left', 'margin-right',
            'display', 'flex-direction', 'justify-content', 'align-items',
            'position', 'top', 'bottom', 'left', 'right', 'width', 'height', 'max-width', 'border', 'border-radius'
        }

    def _calculate_specificity(self, selector: str, source_order: int) -> tuple:
        """
        Calculates CSS Specificity tuple: (inline, ids, classes, tags, source_order)
        """
        # Exclude pseudo elements for core mapping
        if ':' in selector:
            selector = re.sub(r':[\w-]+(?:\([^)]*\))?', '', selector)

        ids = selector.count('#')
        classes = selector.count('.') + selector.count('[')
        
        # Tags are generic words not prefixed by ID/Class triggers
        tags = len(re.findall(r'(?:^|[\s>+~]+)([a-zA-Z0-9]+)', selector))
        
        return (0, ids, classes, tags, source_order)

    def resolve(self, html_content: str, css_content: str) -> Tuple[BeautifulSoup, Dict[int, Dict[str, str]]]:
        """
        Performs the heavy mapping of CSS definitions onto HTML targets.
        Yields a modified parsed HTML and an element style map.
        id(bs4_element) -> { property -> value }
        """
        logger.info("resolving_css_cascade_started")
        soup = BeautifulSoup(html_content, 'lxml')
        
        # Collect internal style tags into global css execution run
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                css_content += "\n" + style_tag.string

        rules = tinycss2.parse_stylesheet(css_content, skip_comments=True, skip_whitespace=True)
        
        element_styles_map = {}
        element_specificity_map = {}
        
        rule_count = 0
        mapped_elements = set()

        for rule in rules:
            if getattr(rule, 'type', None) == 'qualified-rule':
                selector = tinycss2.serialize(rule.prelude).strip()
                decls = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
                
                # Fast track declarations matching allowed properties
                valid_decls = []
                for decl in decls:
                    if getattr(decl, 'type', None) == 'declaration':
                        prop = decl.lower_name
                        if prop in self.allowed_props or prop.startswith('--'):
                            valid_decls.append((prop, tinycss2.serialize(decl.value).strip()))
                
                if not valid_decls:
                    continue

                rule_count += 1
                for sub_sel in selector.split(','):
                    sub_sel = sub_sel.strip()
                    if not sub_sel:
                        continue
                        
                    # Filter interactive pseudo classes but ALLOW structural pseudo classes
                    dynamic_triggers = [':hover', ':active', ':focus', ':visited', '::before', '::after', ':focus-within']
                    if any(t in sub_sel for t in dynamic_triggers):
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
                            current_spec = element_specificity_map[el_id].get(prop, ((-1, -1, -1, -1, -1), ""))[0]
                            if spec >= current_spec:
                                element_specificity_map[el_id][prop] = (spec, val)
        
        # Evaluate Inline Styles Overrides
        for el in soup.find_all(style=True):
            el_id = id(el)
            mapped_elements.add(el_id)
            if el_id not in element_specificity_map:
                element_specificity_map[el_id] = {}
                
            inline_css = el['style']
            inline_decls = tinycss2.parse_declaration_list(inline_css, skip_comments=True, skip_whitespace=True)
            for decl in inline_decls:
                if getattr(decl, 'type', None) == 'declaration':
                    prop = decl.lower_name
                    if prop in self.allowed_props or prop.startswith('--'):
                        val = tinycss2.serialize(decl.value).strip()
                        element_specificity_map[el_id][prop] = ((1, 0, 0, 0, 0), val)
                        
        # Condense specificity map down into final literal dict
        for el_id, props in element_specificity_map.items():
            element_styles_map[el_id] = {p: props[p][1] for p in props}
            
        logger.info("resolving_css_cascade_finished", rules_evaluated=rule_count, elements_styled=len(mapped_elements))
            
        return soup, element_styles_map
