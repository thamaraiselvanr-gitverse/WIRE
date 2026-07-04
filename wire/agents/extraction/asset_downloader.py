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


class AssetDownloader:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient()

    async def download_assets(
        self, page_url: str, html_content: str, asset_dir: str
    ) -> tuple[str, list[str]]:
        soup = BeautifulSoup(html_content, "html.parser")
        downloaded_assets: List[str] = []

        async def fetch_and_save(
            orig_url: str, asset_type: str, source_url: Optional[str] = None
        ) -> str:
            if orig_url.startswith("data:"):
                return orig_url

            base_reference_url = source_url if source_url else page_url
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

        # 4. Inline <style> tags
        for tag in soup.find_all("style"):
            if tag.string:
                new_css = await process_css_text(str(tag.string), page_url)
                tag.string.replace_with(new_css)  # type: ignore[attr-defined]

        # 5. Inline style= attributes
        for tag in soup.find_all(style=True):
            if tag.get("style"):
                new_style = await process_css_text(str(tag["style"]), page_url)
                tag["style"] = new_style

        return str(soup), downloaded_assets

    async def _process_css_urls(
        self,
        css_text: str,
        source_url: str,
        asset_dir: str,
        downloaded_assets: List[Any],
    ) -> str:
        # Find all url(...)
        matches = URL_REGEX.findall(css_text)
        if not matches:
            return css_text

        unique_urls = list(set(matches))
        for old_url in unique_urls:
            # Avoid processing data URIs
            if old_url.startswith("data:"):
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
