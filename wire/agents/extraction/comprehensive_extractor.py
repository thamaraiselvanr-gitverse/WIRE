import re

import structlog
from playwright.async_api import Page

logger = structlog.get_logger(__name__)


# In-browser extraction: uses getComputedStyle + document.styleSheets so values
# reflect the resolved cascade (imported sheets, computed fonts/colors) rather
# than statically-parsed CSS. Returns a JSON-serializable structured report
# spanning meta/SEO, design tokens, typography, color palette, webfonts,
# animations, responsive breakpoints, icon library, accessibility, and a
# component inventory — the analyzable "design knowledge" side of the clone.
_EXTRACT_JS = r"""
() => {
  const q = (s) => Array.from(document.querySelectorAll(s));
  const out = {};

  // ── 1. Meta & SEO ──
  const metaTags = {};
  q('meta').forEach(m => {
    const k = m.getAttribute('name') || m.getAttribute('property')
      || m.getAttribute('http-equiv') || (m.hasAttribute('charset') ? 'charset' : null);
    if (k) metaTags[k] = m.getAttribute('content') || m.getAttribute('charset') || '';
  });
  out.meta = metaTags;
  out.title = document.title;
  out.lang = document.documentElement.getAttribute('lang') || '';
  out.links = q('link').map(l => ({
    rel: l.getAttribute('rel') || '', href: l.getAttribute('href') || '',
    type: l.getAttribute('type') || '', sizes: l.getAttribute('sizes') || '',
    media: l.getAttribute('media') || '',
  }));
  out.json_ld = q('script[type="application/ld+json"]').map(s => (s.textContent || '').slice(0, 4000));

  // ── 2/5. :root design tokens + @font-face / @keyframes / media breakpoints ──
  const cssVars = {};
  const fontFaces = [];
  const keyframes = [];
  const breakpoints = new Set();
  for (const sheet of Array.from(document.styleSheets)) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    if (!rules) continue;
    for (const rule of Array.from(rules)) {
      try {
        if (rule.type === 1 && rule.selectorText === ':root' && rule.style) {
          for (const prop of Array.from(rule.style)) {
            if (prop.startsWith('--')) cssVars[prop] = rule.style.getPropertyValue(prop).trim();
          }
        } else if (rule.type === 5) {  // @font-face
          fontFaces.push({
            family: rule.style.getPropertyValue('font-family'),
            weight: rule.style.getPropertyValue('font-weight'),
            display: rule.style.getPropertyValue('font-display'),
            src: (rule.style.getPropertyValue('src') || '').slice(0, 200),
          });
        } else if (rule.type === 7) {  // @keyframes
          keyframes.push(rule.name);
        } else if (rule.type === 4) {  // @media
          const cond = rule.conditionText || (rule.media && rule.media.mediaText) || '';
          (cond.match(/\d+px/g) || []).forEach(p => breakpoints.add(p));
        }
      } catch (e) { /* skip malformed rule */ }
    }
  }
  out.css_variables = cssVars;
  out.font_faces = fontFaces;
  out.keyframes = keyframes;
  out.breakpoints = Array.from(breakpoints).sort((a, b) => parseInt(a) - parseInt(b));

  // ── 2. Color palette (frequency-ranked from computed styles) ──
  const els = q('*').slice(0, 4000);
  const colorCount = {};
  const fontFamilies = {};
  els.forEach(el => {
    const cs = getComputedStyle(el);
    [cs.color, cs.backgroundColor, cs.borderTopColor].forEach(c => {
      if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') {
        colorCount[c] = (colorCount[c] || 0) + 1;
      }
    });
    if (cs.fontFamily) fontFamilies[cs.fontFamily] = (fontFamilies[cs.fontFamily] || 0) + 1;
  });
  out.color_palette = Object.entries(colorCount)
    .sort((a, b) => b[1] - a[1]).slice(0, 24)
    .map(([color, count]) => ({ color, count }));
  out.font_families = Object.entries(fontFamilies)
    .sort((a, b) => b[1] - a[1]).slice(0, 8).map(([f]) => f);

  // ── 3. Typography scale (computed, per level) ──
  const typography = {};
  ['h1','h2','h3','h4','h5','h6','p','a','button','body'].forEach(sel => {
    const el = sel === 'body' ? document.body : document.querySelector(sel);
    if (el) {
      const cs = getComputedStyle(el);
      typography[sel] = {
        font_family: cs.fontFamily, font_size: cs.fontSize, font_weight: cs.fontWeight,
        line_height: cs.lineHeight, letter_spacing: cs.letterSpacing,
        text_transform: cs.textTransform,
      };
    }
  });
  out.typography = typography;

  // ── 22. Accessibility inventory ──
  out.accessibility = {
    landmarks: {
      header: q('header').length, nav: q('nav').length, main: q('main').length,
      footer: q('footer').length, aside: q('aside').length,
    },
    headings: { h1: q('h1').length, h2: q('h2').length, h3: q('h3').length },
    images_total: q('img').length,
    images_with_alt: q('img[alt]').length,
    aria_label: q('[aria-label],[aria-labelledby]').length,
    aria_hidden: q('[aria-hidden]').length,
    roles: q('[role]').length,
    lang_set: !!document.documentElement.getAttribute('lang'),
    skip_link: !!document.querySelector('a[href^="#"]'),
  };

  // ── Component inventory (7/9/10) ──
  out.components = {
    buttons: q('button,[role="button"],.btn,a.button').length,
    forms: q('form').length,
    inputs: q('input,textarea,select').length,
    dialogs: q('dialog,[role="dialog"],.modal').length,
    tabs: q('[role="tab"],.tab').length,
    accordions: q('details,[class*="accordion"]').length,
    carousels: q('[class*="carousel"],[class*="slider"],[class*="swiper"]').length,
    tables: q('table').length,
    videos: q('video').length,
    audios: q('audio').length,
    iframes: q('iframe').length,
    svgs: q('svg').length,
    pictures: q('picture').length,
    custom_elements: Array.from(new Set(
      q('*').map(e => e.tagName.toLowerCase()).filter(t => t.includes('-'))
    )).slice(0, 40),
  };

  return out;
}
"""


class ComprehensiveExtractor:
    """Structured design-knowledge extraction spanning ~10 checklist categories.

    Runs a single in-browser pass (computed styles + stylesheet rules) to build
    an analyzable report: meta/SEO, ``:root`` tokens, typography, frequency-ranked
    color palette, webfonts, animations, responsive breakpoints, icon library,
    accessibility inventory, and a component inventory.
    """

    async def extract(self, page: Page) -> dict:
        logger.info("comprehensive_extraction_started")
        try:
            report = await page.evaluate(_EXTRACT_JS)
        except Exception as e:
            logger.warning("comprehensive_extraction_failed", error=str(e))
            return {"error": str(e)}

        # Icon library detection is cheap to do on the outer HTML.
        try:
            html = await page.content()
            report["icon_library"] = self.detect_icon_library(html)
        except Exception:
            report["icon_library"] = "unknown"

        logger.info(
            "comprehensive_extraction_complete",
            css_vars=len(report.get("css_variables", {})),
            palette=len(report.get("color_palette", [])),
            breakpoints=len(report.get("breakpoints", [])),
            components=sum(
                v for v in report.get("components", {}).values() if isinstance(v, int)
            ),
        )
        return report

    @staticmethod
    def detect_icon_library(html: str) -> str:
        """Identify the icon system from class/name patterns in the markup."""
        checks = [
            (r"font-?awesome|\bfa-[a-z]", "font-awesome"),
            (r"material-icons|material-symbols", "material"),
            (r"lucide", "lucide"),
            (r"heroicon", "heroicons"),
            (r"bootstrap-icons|\bbi-[a-z]", "bootstrap-icons"),
            (r"phosphor|\bph-[a-z]", "phosphor"),
            (r"feather", "feather"),
            (r"iconify", "iconify"),
            (r"remixicon|\bri-[a-z]", "remixicon"),
        ]
        for pattern, name in checks:
            if re.search(pattern, html, re.IGNORECASE):
                return name
        if "<svg" in html.lower():
            return "inline-svg"
        return "unknown"
