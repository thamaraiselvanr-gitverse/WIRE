"""Headless-fingerprint evasion for authorized reconstruction.

Headless Chromium leaks a handful of signals that bot-protection scripts key
on: ``navigator.webdriver``, an empty plugin list, a missing ``window.chrome``,
a WebGL vendor of "Google SwiftShader", ``navigator.permissions`` returning
``denied`` for notifications while ``Notification.permission`` says ``default``,
and so on. Real sites gate content behind these, so a reconstruction tool that
cannot present as an ordinary browser simply fails to capture them.

This applies the well-known evasion set as a single init script (mirroring
puppeteer-extra-stealth / playwright-stealth) plus context-level fingerprint
arguments. It is for cloning pages the operator is authorized to reconstruct.
"""

from typing import Any

from playwright.async_api import BrowserContext

# One init script covering the standard headless tells. Kept as a single
# document-start script so every frame/navigation gets a consistent identity.
# NOTE: add_init_script runs this text as a script body — it must be plain
# statements, not an arrow function (which would be defined but never called).
_STEALTH_JS = r"""
{
  // 1. navigator.webdriver — the canonical headless flag.
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  // 2. window.chrome — present on real Chrome, absent in headless.
  if (!window.chrome) {
    window.chrome = { runtime: {}, app: { isInstalled: false }, csi: () => {}, loadTimes: () => {} };
  }

  // 3. Plugins + mimeTypes — headless reports an empty list.
  const pluginData = [
    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
    { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
  ];
  const fakePlugins = pluginData.map(p => {
    const plugin = Object.create(Plugin.prototype);
    Object.defineProperties(plugin, {
      name: { value: p.name }, filename: { value: p.filename },
      description: { value: p.description }, length: { value: 1 },
    });
    return plugin;
  });
  Object.defineProperty(navigator, 'plugins', {
    get: () => {
      const arr = Object.create(PluginArray.prototype);
      fakePlugins.forEach((p, i) => { arr[i] = p; });
      Object.defineProperty(arr, 'length', { value: fakePlugins.length });
      return arr;
    },
  });

  // 4. languages — headless can report an empty array.
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

  // 5. Hardware fingerprint — SwiftShader defaults are obvious tells.
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

  // 6. permissions.query — align Notification permission with the real API.
  const originalQuery = window.navigator.permissions &&
    window.navigator.permissions.query;
  if (originalQuery) {
    window.navigator.permissions.query = (parameters) =>
      parameters && parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);
  }

  // 7. WebGL vendor/renderer — mask SwiftShader as consumer Intel hardware.
  const patchGL = (proto) => {
    if (!proto) return;
    const getParameter = proto.getParameter;
    proto.getParameter = function (param) {
      if (param === 37445) return 'Intel Inc.';               // UNMASKED_VENDOR_WEBGL
      if (param === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
      return getParameter.apply(this, [param]);
    };
  };
  try { patchGL(WebGLRenderingContext.prototype); } catch (e) {}
  try { patchGL(WebGL2RenderingContext.prototype); } catch (e) {}

  // 8. Chrome-only: navigator.connection presence.
  if (!navigator.connection) {
    Object.defineProperty(navigator, 'connection', {
      get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }),
    });
  }
}
"""


class StealthManager:
    """Presents the browser as an ordinary desktop Chrome instance."""

    @staticmethod
    async def apply_stealth(context: BrowserContext) -> None:
        """Install the full evasion suite on every page in ``context``."""
        await context.add_init_script(_STEALTH_JS)

    @staticmethod
    def context_fingerprint() -> dict[str, Any]:
        """Context-creation kwargs that round out a plausible desktop identity.

        Merge into ``browser.new_context(**args)``; complements the init script
        by aligning locale, timezone, colour scheme, and device scale so the
        JS-visible fingerprint and the HTTP/context-level one agree.
        """
        return {
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "color_scheme": "light",
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
            "java_script_enabled": True,
        }
