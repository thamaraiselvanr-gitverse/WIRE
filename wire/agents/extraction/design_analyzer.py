import structlog
import tinycss2
from typing import Dict, Any

logger = structlog.get_logger(__name__)

class DesignAnalyzer:
    def extract_design_architecture(self, html_content: str, css_content: str) -> Dict[str, Any]:
        """
        Real world implementation uses AST parsing for CSS via tinycss2.
        """
        logger.info("extracting_design_architecture")
        
        colors = {}
        typography = {}
        spacing = {}
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, 'lxml')
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                css_content += "\n" + style_tag.string

        rules = tinycss2.parse_stylesheet(css_content, skip_comments=True, skip_whitespace=True)
        
        for rule in rules:
            if getattr(rule, 'type', None) == 'qualified-rule':
                decls = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
                for decl in decls:
                    if getattr(decl, 'type', None) == 'declaration':
                        prop = decl.lower_name
                        val = tinycss2.serialize(decl.value).strip()
                        
                        if prop in ('color', 'background-color', 'background'):
                            if '#' in val or 'rgb' in val or 'hsl' in val:
                                colors[val] = True
                        elif prop == 'font-family':
                            typography[val] = True
                        elif prop in ('margin', 'padding', 'margin-top', 'margin-bottom', 'margin-left', 'margin-right', 'padding-top', 'padding-bottom', 'padding-left', 'padding-right'):
                            if 'px' in val or 'rem' in val or 'em' in val:
                                spacing[val] = True
                                
        colors_dict = {f"color-{i}": v for i, v in enumerate(colors.keys(), 1)}
        typography_dict = {f"font-{i}": v for i, v in enumerate(typography.keys(), 1)}
        spacing_dict = {f"space-{i}": v for i, v in enumerate(spacing.keys(), 1)}

        if not colors_dict: colors_dict = {"primary": "#000000", "background": "#ffffff"}
        if not typography_dict: typography_dict = {"base": "Arial, sans-serif"}
        if not spacing_dict: spacing_dict = {"sm": "8px", "md": "16px"}

        return {
            "colors": colors_dict,
            "typography": typography_dict,
            "spacing": spacing_dict
        }
