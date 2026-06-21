import os
import urllib.parse
from bs4 import BeautifulSoup
import httpx
import structlog
import re
import asyncio

logger = structlog.get_logger(__name__)

URL_REGEX = re.compile(r"url\(\s*['\"]?(.*?)['\"]?\s*\)")

class AssetDownloader:
    def __init__(self):
        self.client = httpx.AsyncClient()

    async def download_assets(self, page_url: str, html_content: str, asset_dir: str) -> tuple[str, list[str]]:
        soup = BeautifulSoup(html_content, 'html.parser')
        downloaded_assets = []
        
        async def fetch_and_save(orig_url: str, asset_type: str, source_url: str = None) -> str:
            if orig_url.startswith('data:'):
                return orig_url
                
            base_reference_url = source_url if source_url else page_url
            full_url = urllib.parse.urljoin(base_reference_url, orig_url)
            parsed_url = urllib.parse.urlparse(full_url)
            filename = os.path.basename(parsed_url.path) or "index"
            
            if not filename.endswith(('.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.woff', '.woff2', '.ttf', '.eot')):
                ext_map = {'link': '.css', 'script': '.js', 'img': '.png', 'bg': '.png'}
                filename += ext_map.get(asset_type, '')
                
            # append hash to avoid filename collision
            safe_name = f"{hash(full_url)}_{filename}"
            local_path = os.path.join(asset_dir, safe_name)
            
            try:
                response = await self.client.get(full_url, follow_redirects=True)
                if response.status_code == 200:
                    content_to_save = response.content
                    
                    # If it's a CSS file, parse it for nested urls
                    if asset_type == 'link' and filename.endswith('.css'):
                        css_text = response.text
                        css_text = await self._process_css_urls(css_text, full_url, asset_dir, downloaded_assets)
                        content_to_save = css_text.encode('utf-8')
                        
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
            return await self._process_css_urls(css_text, base_url, asset_dir, downloaded_assets)

        self._process_css_urls_proxy = fetch_and_save 

        # 1. External CSS
        for tag in soup.find_all('link', rel='stylesheet'):
            if tag.get('href'):
                new_href = await fetch_and_save(tag['href'], 'link')
                tag['href'] = new_href
                if tag.has_attr('crossorigin'):
                    del tag['crossorigin']
                if tag.has_attr('integrity'):
                    del tag['integrity']
                
        # 2. External JS
        for tag in soup.find_all('script', src=True):
            if tag.get('src'):
                new_src = await fetch_and_save(tag['src'], 'script')
                tag['src'] = new_src
                if tag.has_attr('crossorigin'):
                    del tag['crossorigin']
                if tag.has_attr('integrity'):
                    del tag['integrity']
                
        # 3. Images
        for tag in soup.find_all('img', src=True):
            if tag.get('src'):
                new_src = await fetch_and_save(tag['src'], 'img')
                tag['src'] = new_src
                
        # 4. Inline <style> tags
        for tag in soup.find_all('style'):
            if tag.string:
                new_css = await process_css_text(tag.string, page_url)
                tag.string.replace_with(new_css)
                
        # 5. Inline style= attributes
        for tag in soup.find_all(style=True):
            if tag.get('style'):
                new_style = await process_css_text(tag['style'], page_url)
                tag['style'] = new_style
                
        return str(soup), downloaded_assets

    async def _process_css_urls(self, css_text: str, source_url: str, asset_dir: str, downloaded_assets: list) -> str:
        # Find all url(...)
        matches = URL_REGEX.findall(css_text)
        if not matches:
            return css_text
            
        unique_urls = list(set(matches))
        for old_url in unique_urls:
            # Avoid processing data URIs
            if old_url.startswith('data:'):
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
                parsed_url = urllib.parse.urlparse(full_url)
                filename = os.path.basename(parsed_url.path) or "index"
                if not filename.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.woff', '.woff2', '.ttf', '.eot')):
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
                    
                    if source_url.endswith('.css'):
                        replacement = safe_name
                    else:
                        replacement = f"assets/{safe_name}"
                        
                    css_text = css_text.replace(old_url, replacement)
            except Exception as e:
                logger.warning("css_asset_download_failed", url=old_url, error=str(e))
                
        return css_text
