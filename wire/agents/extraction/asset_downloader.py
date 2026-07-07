import os
import re
import urllib.parse
from typing import Any, List, Optional

import httpx
import structlog
from bs4 import BeautifulSoup

from wire.utils.url_guard import is_disallowed_subresource

logger = structlog.get_logger(__name__)

URL_REGEX = re.compile(r"url\(\s*['\"]?(.*?)['\"]?\s*\)")
# @import url("x.css") | @import 'x.css', with optional media/layer conditions.
IMPORT_REGEX = re.compile(
    r"""@import\s+(?:url\(\s*['\"]?(?P<u>[^'\")]+)['\"]?\s*\)"""
    r"""|['\"](?P<s>[^'\"]+)['\"])(?P<cond>[^;]*);""",
    re.IGNORECASE,
)


_UNFETCHABLE_SCHEMES = ("javascript:", "mailto:", "tel:", "about:", "blob:")


def _is_unfetchable(url: str) -> bool:
    """URLs that must never be fetched: in-page fragments and non-HTTP schemes."""
    u = url.strip().lower()
    return u.startswith("#") or u.startswith(_UNFETCHABLE_SCHEMES)


class AssetDownloader:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient()
        # Guards against @import cycles within a single download_assets run.
        self._seen_css_imports: set[str] = set()

    async def download_assets(
        self, page_url: str, html_content: str, asset_dir: str
    ) -> tuple[str, list[str]]:
        soup = BeautifulSoup(html_content, "html.parser")
        downloaded_assets: List[str] = []
        self._seen_css_imports = set()

        # A <base href> retargets every relative URL on the page; resolve
        # against it instead of the document URL when present.
        base_tag = soup.find("base", href=True)
        base_url = (
            urllib.parse.urljoin(page_url, str(base_tag["href"]))
            if base_tag
            else page_url
        )

        async def fetch_and_save(
            orig_url: str, asset_type: str, source_url: Optional[str] = None
        ) -> str:
            if orig_url.startswith("data:") or _is_unfetchable(orig_url):
                return orig_url

            base_reference_url = source_url if source_url else base_url
            full_url = urllib.parse.urljoin(base_reference_url, orig_url)

            # Sub-resource SSRF guard: a (possibly attacker-controlled) page must
            # not make the server fetch an internal address via an asset URL.
            if is_disallowed_subresource(full_url):
                logger.warning("asset_ssrf_blocked", url=full_url)
                return orig_url

            parsed_url = urllib.parse.urlparse(full_url)
            filename = os.path.basename(parsed_url.path) or "index"

            if not filename.endswith(
                (
                    ".css",
                    ".js",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".gif",
                    ".svg",
                    ".webp",
                    ".avif",
                    ".ico",
                    ".woff",
                    ".woff2",
                    ".ttf",
                    ".eot",
                    ".mp4",
                    ".webm",
                    ".ogg",
                    ".ogv",
                    ".mov",
                    ".m4v",
                    ".mp3",
                    ".wav",
                    ".m4a",
                    ".vtt",
                    ".webmanifest",
                )
            ):
                ext_map = {"link": ".css", "script": ".js", "img": ".png", "bg": ".png"}
                filename += ext_map.get(asset_type, "")

            # append hash to avoid filename collision
            safe_name = f"{hash(full_url)}_{filename}"
            local_path = os.path.join(asset_dir, safe_name)

            try:
                response = await self.client.get(full_url, follow_redirects=True)
                if response.status_code == 200:
                    content_to_save = response.content

                    # If it's a CSS file, parse it for nested urls
                    if asset_type == "link" and filename.endswith(".css"):
                        css_text = response.text
                        css_text = await self._process_css_urls(
                            css_text, full_url, asset_dir, downloaded_assets
                        )
                        content_to_save = css_text.encode("utf-8")

                    with open(local_path, "wb") as f:
                        f.write(content_to_save)
                    downloaded_assets.append(local_path)

                    # If this was called from inside a CSS file, the path relative to index.html is 'assets/...'
                    return f"assets/{safe_name}"
            except Exception as e:
                logger.warning("asset_download_failed", url=full_url, error=str(e))

            return orig_url

        # Helper to process CSS text and replace url()
        async def process_css_text(css_text: str, base_url: str) -> str:
            return await self._process_css_urls(
                css_text, base_url, asset_dir, downloaded_assets
            )

        self._process_css_urls_proxy = fetch_and_save

        async def rewrite_srcset(value: str, asset_type: str) -> str:
            """Localize each candidate in a ``srcset`` list, keeping descriptors.

            A ``srcset`` is ``url [descriptor]`` entries joined by commas, e.g.
            ``a.jpg 1x, b.jpg 2x`` or ``a.jpg 400w, b.jpg 800w``.
            """
            out = []
            for candidate in value.split(","):
                candidate = candidate.strip()
                if not candidate:
                    continue
                bits = candidate.split(None, 1)
                url = bits[0]
                descriptor = f" {bits[1]}" if len(bits) > 1 else ""
                if url.startswith("data:"):
                    out.append(f"{url}{descriptor}")
                else:
                    new_url = await fetch_and_save(url, asset_type)
                    out.append(f"{new_url}{descriptor}")
            return ", ".join(out)

        # 1. External CSS
        for tag in soup.find_all("link", rel="stylesheet"):
            if tag.get("href"):
                new_href = await fetch_and_save(str(tag["href"]), "link")
                tag["href"] = new_href
                if tag.has_attr("crossorigin"):
                    del tag["crossorigin"]
                if tag.has_attr("integrity"):
                    del tag["integrity"]

        # 2. External JS
        for tag in soup.find_all("script", src=True):
            if tag.get("src"):
                new_src = await fetch_and_save(str(tag["src"]), "script")
                tag["src"] = new_src
                if tag.has_attr("crossorigin"):
                    del tag["crossorigin"]
                if tag.has_attr("integrity"):
                    del tag["integrity"]

        # 3. Images
        for tag in soup.find_all("img", src=True):
            if tag.get("src"):
                new_src = await fetch_and_save(str(tag["src"]), "img")
                tag["src"] = new_src

        # 3b. Responsive-image srcset + lazy-loading data attributes on <img>.
        for tag in soup.find_all("img"):
            if tag.get("srcset"):
                tag["srcset"] = await rewrite_srcset(str(tag["srcset"]), "img")
            if tag.get("data-srcset"):
                tag["data-srcset"] = await rewrite_srcset(
                    str(tag["data-srcset"]), "img"
                )
            for attr in ("data-src", "data-original", "data-lazy-src", "data-fallback"):
                if tag.get(attr):
                    tag[attr] = await fetch_and_save(str(tag[attr]), "img")

        # 3c. <picture>/<video>/<audio> <source> variants (srcset or src).
        for tag in soup.find_all("source"):
            if tag.get("srcset"):
                tag["srcset"] = await rewrite_srcset(str(tag["srcset"]), "img")
            if tag.get("src"):
                tag["src"] = await fetch_and_save(str(tag["src"]), "media")

        # 3d. Media elements: <video>/<audio> src, poster image, <track> src.
        for tag in soup.find_all(["video", "audio"]):
            if tag.get("src"):
                tag["src"] = await fetch_and_save(str(tag["src"]), "media")
            if tag.get("poster"):
                tag["poster"] = await fetch_and_save(str(tag["poster"]), "img")
        for tag in soup.find_all("track", src=True):
            tag["src"] = await fetch_and_save(str(tag["src"]), "media")

        # 3e. Icons, favicons, and web-app manifest.
        icon_rels = {
            "icon",
            "shortcut icon",
            "apple-touch-icon",
            "apple-touch-icon-precomposed",
            "mask-icon",
            "manifest",
        }
        for tag in soup.find_all("link", href=True):
            rels = {r.lower() for r in (tag.get("rel") or [])}
            if rels & icon_rels:
                tag["href"] = await fetch_and_save(str(tag["href"]), "icon")

        # 3f. Social-preview images referenced from <meta content="...">
        # (og:image, twitter:image, msapplication tile, schema.org image).
        meta_image_keys = {
            "og:image",
            "og:image:url",
            "og:image:secure_url",
            "twitter:image",
            "twitter:image:src",
            "msapplication-tileimage",
            "image",
        }
        for tag in soup.find_all("meta", content=True):
            key = str(
                tag.get("property") or tag.get("name") or tag.get("itemprop") or ""
            ).lower()
            if key in meta_image_keys:
                tag["content"] = await fetch_and_save(str(tag["content"]), "img")

        # 3g. SVG sprite references: <use href="sprite.svg#icon"> pulls a symbol
        # from an external file that must be localized (the #fragment is kept).
        for tag in soup.find_all("use"):
            ref_raw = tag.get("href") or tag.get("xlink:href")
            ref = str(ref_raw) if ref_raw else ""
            if ref and "#" in ref and not ref.startswith("#"):
                file_part, frag = ref.split("#", 1)
                local = await fetch_and_save(file_part, "img")
                attr = "href" if tag.get("href") else "xlink:href"
                tag[attr] = f"{local}#{frag}"

        # 4. Inline <style> tags
        for tag in soup.find_all("style"):
            if tag.string:
                new_css = await process_css_text(str(tag.string), base_url)
                tag.string.replace_with(new_css)  # type: ignore[attr-defined]

        # 5. Inline style= attributes
        for tag in soup.find_all(style=True):
            if tag.get("style"):
                new_style = await process_css_text(str(tag["style"]), base_url)
                tag["style"] = new_style

        return str(soup), downloaded_assets

    async def _process_css_imports(
        self,
        css_text: str,
        source_url: str,
        asset_dir: str,
        downloaded_assets: List[Any],
    ) -> str:
        """Fetch, recursively localize, and rewrite ``@import`` statements.

        Each imported stylesheet is downloaded as CSS (not an opaque blob),
        run back through ``_process_css_urls`` so its own ``url()`` refs and
        nested imports are localized too, then saved and the ``@import``
        rewritten to the local copy. Bare-string imports (``@import "x.css"``)
        are handled as well as ``@import url(...)``. Import cycles are guarded.
        """
        imports = list(IMPORT_REGEX.finditer(css_text))
        if not imports:
            return css_text

        for match in imports:
            href = match.group("u") or match.group("s")
            if not href or href.startswith("data:"):
                continue
            try:
                full_url = urllib.parse.urljoin(source_url, href)
                if is_disallowed_subresource(full_url):
                    logger.warning("css_import_ssrf_blocked", url=full_url)
                    continue
                if full_url in self._seen_css_imports:
                    continue
                self._seen_css_imports.add(full_url)

                response = await self.client.get(full_url, follow_redirects=True)
                if response.status_code != 200:
                    continue

                nested_css = await self._process_css_urls(
                    response.text, full_url, asset_dir, downloaded_assets
                )

                filename = os.path.basename(urllib.parse.urlparse(full_url).path)
                if not filename.endswith(".css"):
                    filename = (filename or "import") + ".css"
                safe_name = f"{hash(full_url)}_{filename}"
                with open(os.path.join(asset_dir, safe_name), "wb") as f:
                    f.write(nested_css.encode("utf-8"))
                downloaded_assets.append(os.path.join(asset_dir, safe_name))

                # A CSS file lives inside assets/ alongside its imports; the
                # HTML/inline case needs the assets/ prefix.
                local_ref = (
                    safe_name if source_url.endswith(".css") else f"assets/{safe_name}"
                )
                cond = match.group("cond").strip()
                replacement = f'@import "{local_ref}"{" " + cond if cond else ""};'
                css_text = css_text.replace(match.group(0), replacement)
            except Exception as e:
                logger.warning("css_import_failed", url=href, error=str(e))

        return css_text

    async def _process_css_urls(
        self,
        css_text: str,
        source_url: str,
        asset_dir: str,
        downloaded_assets: List[Any],
    ) -> str:
        # Resolve @import chains first so imported sheets are localized as CSS
        # rather than downloaded as opaque blobs by the url() pass below.
        css_text = await self._process_css_imports(
            css_text, source_url, asset_dir, downloaded_assets
        )

        # Find all url(...)
        matches = URL_REGEX.findall(css_text)
        if not matches:
            return css_text

        unique_urls = list(set(matches))
        for old_url in unique_urls:
            # Skip data URIs, in-page SVG fragment refs (url(#filter)), and
            # non-fetchable schemes — fetching those would 404 or error.
            if old_url.startswith("data:") or _is_unfetchable(old_url):
                continue

            # Use fetch_and_save indirectly. Note: The return of fetch_and_save is `assets/name`
            # which is relative to index.html. CSS files in `assets/` relative to `assets/` need adjustment.
            # But here `fetch_and_save` returns `assets/name`. Since we rewrite HTML index.html,
            # For CSS file saving, we are rewriting the same `assets/name`. Wait...
            # If the CSS file itself is in `assets/`, then `url(assets/name)` is broken. It should be `url(name)`.
            # However, for simplicity of Phase 1MVP, we put EVERYTHING in `assets/` and the downloaded CSS file
            # uses `url(name_of_asset_in_same_folder)`.

            # Let's cleanly fetch it
            try:
                full_url = urllib.parse.urljoin(source_url, old_url)
                if is_disallowed_subresource(full_url):
                    logger.warning("css_asset_ssrf_blocked", url=full_url)
                    continue
                parsed_url = urllib.parse.urlparse(full_url)
                filename = os.path.basename(parsed_url.path) or "index"
                if not filename.endswith(
                    (
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".gif",
                        ".svg",
                        ".webp",
                        ".woff",
                        ".woff2",
                        ".ttf",
                        ".eot",
                    )
                ):
                    filename += ".png"
                safe_name = f"{hash(full_url)}_{filename}"
                local_path = os.path.join(asset_dir, safe_name)

                response = await self.client.get(full_url, follow_redirects=True)
                if response.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    downloaded_assets.append(local_path)

                    # Determine replacement:
                    # If this source_url is a CSS file inside `assets/`, we just need the filename.
                    # If it's inline in HTML, we need `assets/filename`.
                    # To be perfectly safe, since we map all assets into `output/domain/assets/`,
                    # if the source was index.html it needs `assets/...`.
                    # If the source was `.css`, it's already in `assets/` so it needs just `...`.

                    if source_url.endswith(".css"):
                        replacement = safe_name
                    else:
                        replacement = f"assets/{safe_name}"

                    css_text = css_text.replace(old_url, replacement)
            except Exception as e:
                logger.warning("css_asset_download_failed", url=old_url, error=str(e))

        return css_text
