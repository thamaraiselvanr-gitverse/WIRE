import re
import urllib.parse

from bs4 import BeautifulSoup


class HtmlSanitizer:
    """
    Centralized HTML Sanitizer using BeautifulSoup.
    Strips script tags, event handlers, unsafe URI protocols, and CSS injections.
    """

    UNSAFE_TAGS = {
        "script",
        "iframe",
        "object",
        "embed",
        "applet",
        "style",
        "meta",
        "noscript",
        "link",
        "title",
        "head",
    }
    SAFE_PROTOCOLS = {"http", "https", "mailto", "tel", ""}

    @staticmethod
    def sanitize_html(html_str: str) -> str:
        """Sanitize a raw HTML fragment."""
        if not html_str:
            return ""

        soup = BeautifulSoup(html_str, "html.parser")

        # 1. Strip blocklisted tags
        for tag in soup.find_all(True):
            if tag.name in HtmlSanitizer.UNSAFE_TAGS:
                tag.decompose()
                continue

            # 2. Sanitize attributes
            attrs = list(tag.attrs.items())
            for attr_name, attr_val in attrs:
                # Remove event handlers
                if attr_name.lower().startswith("on"):
                    del tag.attrs[attr_name]
                    continue

                # Check URI values
                if attr_name.lower() in {"href", "src", "action", "formaction"}:
                    if not HtmlSanitizer._is_safe_uri(attr_val):
                        del tag.attrs[attr_name]
                        continue

                # Sanitize style attribute
                if attr_name.lower() == "style":
                    sanitized_style = HtmlSanitizer._sanitize_style_string(attr_val)
                    if sanitized_style:
                        tag.attrs[attr_name] = sanitized_style
                    else:
                        del tag.attrs[attr_name]

        return "".join(str(child) for child in soup.children)

    @staticmethod
    def _is_safe_uri(uri: str) -> bool:
        """Return True if the URI uses a safe protocol or relative path."""
        if not uri:
            return True
        uri_str = str(uri).strip()

        # Check for javascript: inline execution
        if uri_str.lower().startswith("javascript:"):
            return False

        try:
            parsed = urllib.parse.urlparse(uri_str)
            return parsed.scheme.lower() in HtmlSanitizer.SAFE_PROTOCOLS
        except Exception:
            return False

    @staticmethod
    def _sanitize_style_string(style_str: str) -> str:
        """Strip dangerous style rules like expression(...) or url(javascript:...).

        Processes each CSS declaration individually so that safe properties
        (e.g. 'color: red') are preserved even when they appear alongside
        dangerous ones (e.g. 'expression(alert(1))').
        """
        if not style_str:
            return ""

        cleaned = style_str.strip()
        if cleaned in {")", "(", "()", ""}:
            return ""

        # Split into individual declarations and evaluate each one
        declarations = [d.strip() for d in cleaned.split(";") if d.strip()]
        safe_declarations = []

        for decl in declarations:
            decl_lower = decl.lower()

            # Skip declarations containing dangerous patterns
            if "expression" in decl_lower:
                continue
            if "javascript:" in decl_lower:
                continue
            if "behavior:" in decl_lower:
                continue

            # Additional check for url() patterns to detect browser-blocked XSS/invalid URLs (e.g. url([bad url]))
            urls = re.findall(r"url\(\s*['\"]?(.*?)['\"]?\s*\)", decl_lower)
            has_unsafe_url = False
            for u in urls:
                u_clean = u.strip()
                if not u_clean:
                    continue
                # Skip safe data URIs
                if u_clean.startswith("data:"):
                    safe_data_prefixes = (
                        "data:image/png",
                        "data:image/jpeg",
                        "data:image/jpg",
                        "data:image/gif",
                        "data:image/webp",
                        "data:image/svg+xml",
                        "data:font/",
                        "data:application/font-woff",
                        "data:application/x-font-woff",
                        "data:application/font-sfnt",
                    )
                    if (
                        not any(
                            u_clean.startswith(prefix) for prefix in safe_data_prefixes
                        )
                        or "javascript" in u_clean
                        or "html" in u_clean
                    ):
                        has_unsafe_url = True
                        break
                    continue
                # Block browser error values, unsafe protocols, or bracket injections
                if (
                    "javascript:" in u_clean
                    or "expression" in u_clean
                    or "behavior:" in u_clean
                ):
                    has_unsafe_url = True
                    break
                if "bad url" in u_clean or "about:" in u_clean or "invalid" in u_clean:
                    has_unsafe_url = True
                    break
                if any(char in u_clean for char in "()[]"):
                    has_unsafe_url = True
                    break
                # Validate protocol using _is_safe_uri
                if not HtmlSanitizer._is_safe_uri(u_clean):
                    has_unsafe_url = True
                    break
            if has_unsafe_url:
                continue

            # Clean any partial expressions or js urls within this declaration
            cleaned_decl = re.sub(
                r"expression\s*\(.*?\)", "", decl, flags=re.IGNORECASE
            )
            cleaned_decl = re.sub(
                r"url\s*\(\s*javascript:.*?\)", "", cleaned_decl, flags=re.IGNORECASE
            )
            cleaned_decl = re.sub(
                r"behavior\s*:", "", cleaned_decl, flags=re.IGNORECASE
            )
            cleaned_decl = cleaned_decl.strip()

            if cleaned_decl and cleaned_decl not in {")", "(", "()"}:
                safe_declarations.append(cleaned_decl)

        return "; ".join(safe_declarations)
