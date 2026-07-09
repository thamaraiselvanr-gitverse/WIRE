"""Opt-in removal of analytics, ad, and tracking-pixel references.

A cloned page keeps every third-party tracker the original shipped: analytics
bootstrap scripts, tag managers, session recorders, ad pixels, and hyperlink
``ping`` beacons. Serving the clone would fire those beacons against the
*original* site's property IDs — leaking the repurposer's traffic to the
source owner's dashboards and violating most analytics ToS. Stripping is
deliberately **opt-in** (``ExecutionRouter.enable_tracker_stripping``): it
changes page behavior, and the default pipeline promise is fidelity.

The stripper is signature-based and conservative: only references whose host
matches a known tracker domain (or whose inline body carries a distinctive
tracker bootstrap token) are removed. First-party scripts are never touched.
"""

import re
import urllib.parse
from typing import Any, Dict, List, Tuple

import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger(__name__)

# Hosts (matched by suffix) that exist to track. Functional third parties
# (CDNs, font hosts, video embeds) are deliberately absent.
TRACKER_DOMAINS: Tuple[str, ...] = (
    "google-analytics.com",
    "googletagmanager.com",
    "googlesyndication.com",
    "googleadservices.com",
    "doubleclick.net",
    "connect.facebook.net",
    "hotjar.com",
    "mixpanel.com",
    "segment.com",
    "segment.io",
    "amplitude.com",
    "clarity.ms",
    "fullstory.com",
    "mouseflow.com",
    "crazyegg.com",
    "matomo.cloud",
    "stats.wp.com",
    "scorecardresearch.com",
    "quantserve.com",
    "js-agent.newrelic.com",
    "nr-data.net",
    "widget.intercom.io",
    "ads-twitter.com",
    "analytics.tiktok.com",
    "snap.licdn.com",
    "px.ads.linkedin.com",
    "mc.yandex.ru",
    "criteo.com",
    "criteo.net",
    "taboola.com",
    "outbrain.com",
    "addthis.com",
    "sharethis.com",
    "plausible.io",
    "usefathom.com",
)

# URL fragments that identify a pixel even on an otherwise-functional domain
# (e.g. facebook.com serves both content and the /tr pixel endpoint).
PIXEL_URL_PATTERNS: Tuple[str, ...] = (
    "facebook.com/tr",
    "google.com/pagead",
)

# Distinctive bootstrap tokens found in inline tracker snippets. Chosen to be
# specific enough that ordinary application code never matches.
INLINE_SIGNATURES = re.compile(
    r"""(
        \bgtag\s*\(            # Google gtag.js bootstrap
        | \bfbq\s*\(           # Meta pixel
        | \b_paq\s*[.[]        # Matomo/Piwik queue
        | \b_hjSettings\b      # Hotjar
        | \bmixpanel\.init\b
        | \banalytics\.load\s*\(   # Segment
        | \bamplitude\.getInstance\b
        | ["']clarity["']      # MS Clarity loader
        | \bttq\.load\b        # TikTok
        | \bsnaptr\s*\(        # Snap
        | \btwq\s*\(           # Twitter/X ads
        | \blintrk\s*\(        # LinkedIn insight
        | \bym\s*\(\s*\d+,     # Yandex Metrika
        | googletagmanager\.com/gtm\.js
    )""",
    re.VERBOSE,
)

# Site-verification metas belong to the original owner, not the repurposer.
VERIFICATION_META_NAMES = {
    "google-site-verification",
    "facebook-domain-verification",
    "msvalidate.01",
    "yandex-verification",
    "p:domain_verify",
    "pinterest-site-verification",
}


def _is_tracker_url(url: str) -> bool:
    """True when the URL's host is a known tracker or matches a pixel path."""
    lowered = url.lower()
    if any(pat in lowered for pat in PIXEL_URL_PATTERNS):
        return True
    host = urllib.parse.urlparse(lowered).netloc.split(":")[0]
    if not host and lowered.startswith("//"):
        host = urllib.parse.urlparse("https:" + lowered).netloc.split(":")[0]
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in TRACKER_DOMAINS)


class TrackerStripper:
    """Remove tracker references from captured HTML, reporting every removal."""

    def strip(self, html: str) -> Tuple[str, Dict[str, Any]]:
        """Return ``(clean_html, report)``.

        Removes: external ``<script src>`` to tracker hosts, inline scripts
        carrying tracker bootstrap signatures, tracking pixels (``<img>`` to
        tracker hosts / pixel endpoints, including inside ``<noscript>``),
        tracker ``<iframe>``s, ``preconnect``/``dns-prefetch`` hints to
        tracker hosts, site-verification ``<meta>`` tags, and hyperlink-audit
        ``ping`` attributes. Everything removed is counted and the matched
        hosts listed, so the operator can audit what changed.
        """
        soup = BeautifulSoup(html, "html.parser")
        removed: Dict[str, int] = {
            "external_scripts": 0,
            "inline_scripts": 0,
            "pixels": 0,
            "iframes": 0,
            "resource_hints": 0,
            "verification_meta": 0,
            "ping_attributes": 0,
        }
        matched_urls: List[str] = []

        for tag in soup.find_all("script", src=True):
            src = str(tag["src"])
            if _is_tracker_url(src):
                matched_urls.append(src)
                tag.decompose()
                removed["external_scripts"] += 1

        for tag in soup.find_all("script", src=False):
            body = tag.string or ""
            if body and INLINE_SIGNATURES.search(body):
                tag.decompose()
                removed["inline_scripts"] += 1

        for tag in soup.find_all("img", src=True):
            src = str(tag["src"])
            if _is_tracker_url(src):
                matched_urls.append(src)
                tag.decompose()
                removed["pixels"] += 1

        for tag in soup.find_all("iframe", src=True):
            src = str(tag["src"])
            if _is_tracker_url(src):
                matched_urls.append(src)
                tag.decompose()
                removed["iframes"] += 1

        for tag in soup.find_all("link", href=True):
            rels = {r.lower() for r in (tag.get("rel") or [])}
            if rels & {"preconnect", "dns-prefetch", "preload", "prefetch"}:
                href = str(tag["href"])
                if _is_tracker_url(href):
                    matched_urls.append(href)
                    tag.decompose()
                    removed["resource_hints"] += 1

        for tag in soup.find_all("meta"):
            name = str(tag.get("name") or "").lower()
            if name in VERIFICATION_META_NAMES:
                tag.decompose()
                removed["verification_meta"] += 1

        for tag in soup.find_all(ping=True):
            del tag["ping"]
            removed["ping_attributes"] += 1

        # Empty <noscript> shells left behind by removed pixels.
        for tag in soup.find_all("noscript"):
            if not tag.get_text(strip=True) and not tag.find(True):
                tag.decompose()

        total = sum(removed.values())
        report: Dict[str, Any] = {
            "total_removed": total,
            "removed": removed,
            "matched_urls": sorted(set(matched_urls)),
        }
        logger.info("trackers_stripped", total=total)
        return str(soup), report
