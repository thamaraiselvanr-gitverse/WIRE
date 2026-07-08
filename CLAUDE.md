# WIRE — Semantic Web Reconstructor

WIRE takes a URL and produces two things from one crawl:

1. **A pixel-faithful clone** — the original HTML with assets localized
   (`AssetDownloader` + `LocalStorage`); this is the high-fidelity output.
2. **A semantic, editable version** — the page reduced to a **Canonical
   Intermediate Design Schema (CIDS)** (a Pydantic tree of tag/attrs/styles/
   children), then run through classify → detect placeholders → reconcile
   intent (LLM) → validate submission → substitute content → recompile
   (HTML / React / Vue). This is the actual product: repurpose someone's
   layout with your own content without breaking it.

## Repo layout

```
wire/
  main.py, service.py            # CLI entry + service wrapper
  orchestrator/execution_router.py   # THE pipeline (~900 lines, start here)
  agents/exploration/            # crawler, fuzzer, region_probe
  agents/observation/            # browser_session (Playwright), spa_detector,
                                 #   shadow_piercer, viewport_renderer, stealth, auth
  agents/extraction/             # asset_downloader, design_analyzer,
                                 #   interaction_recorder, legal_detector, network_monitor
  schema/                        # canonical.py (CIDS), style_mapper.py (CascadeResolver),
                                 #   input_blueprint, semantic_schema, submission_schema, ...
  compilers/                     # html_compiler, react_adapter, vue_adapter, sanitizer
  semantic/                      # llm_guard, llm_client (Gemini), section_classifier,
                                 #   placeholder_detector, intent_reconciler, form_schema_compiler
  generation/                    # submission_validator, substitution_mapper,
                                 #   image_ingestion, transformation_prompt_generator
  layout/                        # section_removal_planner, layout_reflow_engine,
                                 #   structural_integrity_validator
  validation/                    # visual_diff.py (pixel diff), structural.py (DOM diff)
  templates/                     # Phase 6 template ecosystem (see gotcha below)
  utils/                         # config, logging, fidelity_scorer
  api/                           # FastAPI backend (auth + main routes, SQLite)
frontend/                        # React + Vite dashboard
tests/                           # pytest suite (unit/, integration/, e2e/, phase*.py)
```

## Setup & run

```bash
# Backend (use a venv — the system python has a broken cryptography/jose combo)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Playwright browser: in the cloud sandbox a chromium build is prebuilt at
# /opt/pw-browsers (PLAYWRIGHT_BROWSERS_PATH). `playwright install` is blocked
# by egress policy and the pinned version may mismatch — browser-driven tests
# may skip/fail there but pass locally after `playwright install chromium`.

# Tests
.venv/bin/python -m pytest tests/ -q

# CLI reconstruction of a single URL
.venv/bin/python -m wire.main <url>

# API + frontend
uvicorn wire.api.main:app --port 8000
cd frontend && npm install && npm run dev      # http://localhost:5173
```

## Pipeline flow (execution_router.py `execute_pipeline`)

legal check → crawl → for each page: capture (Playwright) → download+localize
assets → design analysis → SPA/shadow-DOM/network/viewport capture → cascade
resolution (`CascadeResolver`) → build CIDS → compile React/Vue → semantic
interpretation (classify/placeholders/form schema) → structural + **visual**
validation feeding `FidelityScorer` → template ecosystem + `.wire` artifact.

Phase 8 (`remove_sections`) and Phase 9 (`generate_transformation_prompt`) are
separate post-run APIs on `ExecutionRouter` that mutate a stored run's CIDS.

## LLM integration

Gemini via the `google-genai` SDK (`from google import genai`), the supported
successor to the deprecated `google-generativeai` package. Key from
`GEMINI_API_KEY` or `GOOGLE_API_KEY`; model override via
`WIRE_LLM_MODEL` (default `gemini-2.0-flash`). All calls route through
`LLMGuard` and **fail closed** (return `None` → heuristic fallback) when no key
is set, so the pipeline runs offline. Live-LLM tests skip without a key.

## Known state / gaps (verified, not aspirational)

- **Fidelity scoring is now real** (as of the accuracy-features branch):
  `FidelityScorer` records perceptual (SSIM) visual + structural similarity and
  caps the score by what was measured. The visual/structural checks score the
  **editable** output (`output_editable.html`, the actual product), not the
  asset-localized clone (kept only as a `*_clone` diagnostic). The visual score
  cap is **SSIM** (`ssim_percent`); raw pixel `similarity_percent` is retained
  as a diagnostic. Previously it always returned ~100% regardless of output
  quality — do not reintroduce that decoupling. Responsive layout is validated
  too: the editable output is re-screenshotted at the 768/480 breakpoint
  widths (matching `ComputedStyleCapturer.DEFAULT_BREAKPOINTS`; originals from
  `ViewportRenderer`'s `tablet`/`mobile_small` viewports) and the **mean**
  breakpoint SSIM is a further cap (`visual_fidelity_breakpoints.json`) — a
  page that only looks right at desktop width is not fully faithful. Low
  breakpoint scores lower the score but are not critical errors.
- **Style capture is browser-first**: `ComputedStyleCapturer` reads
  `getComputedStyle` per element into the CIDS (keyed by the parser's
  `node_path`), and the parser prefers those engine-resolved values over the
  heuristic `CascadeResolver`, falling back to it when absent. url()-bearing
  props are excluded from computed capture (they resolve to absolute URLs) and
  come from the localized cascade instead. Dark-mode styles are captured too
  (`capture_color_scheme` emulates `prefers-color-scheme: dark`) and merge into
  the same responsive-delta map as `@media (prefers-color-scheme: dark)`.
- **Capture fires lazy content first**: `BrowserSession.trigger_lazy_content`
  scrolls the full page height (capped steps, returns to top) before
  `page.content()`, so IntersectionObserver-based lazy images and scroll-reveal
  sections are materialized in the snapshot.
- **`AssetDownloader` dedups and normalizes**: per-run URL cache (each URL
  fetched once) + sha256 content-hash dedup (identical bytes from different
  URLs → one local file; CSS/manifests exempt since their rewritten refs are
  source-relative). Declared charsets are normalized to UTF-8 (the clone is
  written as UTF-8). PWA manifest icons/screenshots and
  `preload`/`prefetch`/`modulepreload` link hrefs are localized; DOCTYPE is
  preserved (never invented for quirks-mode pages).
- **`CascadeResolver` now gates via a denylist** (`denied_props` +
  `_accept_prop`): every property is kept except explicitly non-visual/
  behavioral ones. `allowed_props` remains only as a reference set. Add to
  `denied_props` (not the allowlist) if a non-visual property leaks in.
- **Repurposing works without an LLM now**: `HeuristicSlotDiscoverer`
  (`semantic/slot_discovery.py`) binds `slot_id`s onto replaceable content
  nodes (leaf text, images) and builds the `InputBlueprint`, so the form schema
  exposes real editable fields offline (previously `total_fields` was always 0 —
  nothing was slot-bound). It mutates the CIDS in place, so the bindings persist
  in `schema_cids.json` and drive substitution. The LLM refines these when
  present; it is no longer required for the product to function.
- **Repurposing success is measured** by `evaluation/repurpose_harness.py`
  (`ExecutionRouter.evaluate_repurpose`): it applies a content payload to the
  CIDS, recompiles `substituted_editable.html`, and scores slot-fill + content-
  presence + structural integrity + **layout safety** (composite in
  `repurpose_report.json`). Honesty guard: nothing repurposed → success 0,
  never a vacuous 100.
- **Content fit is checked** by `evaluation/layout_safety.py`
  (`ContentFitValidator`): substituted content that overflows its slot (text
  ≫ original or over the slot's `max_length`), leaves a required slot empty, or
  changes an image's aspect ratio is flagged as a risk and lowers the repurpose
  score — so "your content without breaking it" is measured, not assumed.
- `Crawler` does real same-domain BFS only when `single_page=False`
  (opt-in via `ExecutionRouter.enable_multi_page_crawl`, default off).
- **Tracker stripping is opt-in** (`ExecutionRouter.enable_tracker_stripping`,
  default off — the default promise is fidelity): `TrackerStripper` removes
  known analytics/pixel/tag-manager scripts, tracker iframes/pixels (incl.
  `<noscript>` shells), tracker resource hints, site-verification metas, and
  `<a ping>` beacons before asset download, writing `tracker_report.json`
  with counts + matched URLs. Signature/domain-based and conservative —
  first-party scripts are never touched.
- Still thin/stubbed: `stealth.py`, `auth_handler.py`, `orchestrator/scheduler.py`
  & `coordinator.py` (single-node simulation), Phase 5 "consensus" (re-renders
  the same URL 3×) and `region_probe` (no real geo egress configured).
- **Interactivity is partially restored** by `layout/interactivity_transformer.py`
  (`InteractivityTransformer`): it detects JS-driven dropdowns (class-signalled
  nested submenus → hidden + `:hover`/`:focus-within` reveal via injected CSS)
  ARIA disclosures (`aria-expanded`+`aria-controls` → native
  `<details>/<summary>`), ARIA tabs (`role=tablist/tab/tabpanel` → `:target`
  anchors + `:has()` default panel), and class-signalled carousels (→ CSS
  scroll-snap track), emitting a **separate** `output_interactive.html`
  (+ `interactivity_report.json`). It never touches the pixel-scored
  `output_editable.html`, so fidelity isn't affected. Carousel autoplay stays
  out of scope (manual swipe/scroll only).
- `html_compiler` flattens styles to inline `style=""` and drops `<style>`/JS —
  inline styles can't express `:hover`/`@media`/animation, so the editable path
  has a lower fidelity ceiling than the raw clone by design.

## Gotchas

- **`.gitignore` `templates/` used to match at any depth**, silently excluding
  the entire `wire/templates/` package from git. It's now scoped to
  `/templates/` (root runtime cache). If `wire/templates/*.py` is missing from a
  fresh clone, that old rule is why — re-add the files.
- `pyproject.toml` is the source of truth for deps; keep it in sync with imports
  (it was previously missing tinycss2/lxml/Pillow/numpy/google-generativeai).

## Dev conventions

Black (line-length 88) + Ruff (E,F,I) + strict Mypy, enforced in
`.github/workflows/ci.yml` alongside `pytest --cov=wire --cov-fail-under=90`.
Google-style docstrings, structlog for logging. Note: the existing tree has a
large pre-existing black/ruff backlog — format the files you touch, don't
reformat the whole repo in unrelated commits.
