from typing import Any, Dict

import structlog
from playwright.async_api import Page

logger = structlog.get_logger(__name__)


class SPADetector:
    """
    Detects SPA/SSR/hydration patterns and selects appropriate rendering strategy.
    Identifies React, Vue, Angular, Svelte, Next.js, Nuxt, and other frameworks.
    """

    async def detect(self, page: Page) -> Dict[str, Any]:
        logger.info("detecting_spa_framework")

        result = await page.evaluate("""
            () => {
                const detection = {
                    is_spa: false,
                    framework: null,
                    ssr: false,
                    hydration: false,
                    signals: [],
                };

                // React detection
                if (window.__REACT_DEVTOOLS_GLOBAL_HOOK__ ||
                    document.querySelector('[data-reactroot]') ||
                    document.querySelector('[data-reactid]')) {
                    detection.is_spa = true;
                    detection.framework = 'react';
                    detection.signals.push('react_detected');
                }

                // Next.js detection
                if (window.__NEXT_DATA__ || document.querySelector('#__next')) {
                    detection.is_spa = true;
                    detection.framework = 'nextjs';
                    detection.ssr = true;
                    detection.hydration = true;
                    detection.signals.push('nextjs_detected');
                }

                // Vue detection
                if (window.__VUE__ || document.querySelector('[data-v-]') ||
                    document.querySelector('#app[data-server-rendered]')) {
                    detection.is_spa = true;
                    detection.framework = 'vue';
                    detection.signals.push('vue_detected');
                }

                // Nuxt detection
                if (window.__NUXT__ || window.$nuxt) {
                    detection.is_spa = true;
                    detection.framework = 'nuxt';
                    detection.ssr = true;
                    detection.hydration = true;
                    detection.signals.push('nuxt_detected');
                }

                // Angular detection
                if (window.ng || document.querySelector('[ng-version]') ||
                    document.querySelector('app-root')) {
                    detection.is_spa = true;
                    detection.framework = 'angular';
                    detection.signals.push('angular_detected');
                }

                // Svelte detection
                if (document.querySelector('[class*="svelte-"]')) {
                    detection.is_spa = true;
                    detection.framework = 'svelte';
                    detection.signals.push('svelte_detected');
                }

                // Generic SPA indicators
                if (document.querySelectorAll('script[type="module"]').length > 0) {
                    detection.signals.push('esm_modules_present');
                }
                if (document.querySelector('script[src*="chunk"]') ||
                    document.querySelector('script[src*="bundle"]')) {
                    detection.signals.push('bundled_js_detected');
                }

                // Check for client-side routing
                const links = document.querySelectorAll('a[href]');
                let hashLinks = 0;
                links.forEach(l => {
                    if (l.href.includes('#') || l.getAttribute('href')?.startsWith('/')) {
                        hashLinks++;
                    }
                });
                if (hashLinks > links.length * 0.5 && links.length > 5) {
                    detection.signals.push('client_side_routing_likely');
                    if (!detection.is_spa) detection.is_spa = true;
                }

                return detection;
            }
        """)

        logger.info(
            "spa_detection_complete",
            is_spa=result["is_spa"],
            framework=result["framework"],
            signals=len(result["signals"]),
        )
        return result  # type: ignore[no-any-return]
