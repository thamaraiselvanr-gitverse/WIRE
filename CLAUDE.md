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
  `FidelityScorer` records pixel-visual + structural similarity and caps the
  score by what was measured. Previously it always returned ~100% regardless of
  output quality — do not reintroduce that decoupling.
- **`CascadeResolver.allowed_props`** is an allowlist; anything not listed is
  dropped from the CIDS/editable path. It now covers grid/flex/transform/
  transition/animation/shadow/etc. Add properties here when fidelity regresses.
- `Crawler` does real same-domain BFS only when `single_page=False`
  (opt-in via `ExecutionRouter.enable_multi_page_crawl`, default off).
- Still thin/stubbed: `stealth.py`, `auth_handler.py`, `orchestrator/scheduler.py`
  & `coordinator.py` (single-node simulation), Phase 5 "consensus" (re-renders
  the same URL 3×) and `region_probe` (no real geo egress configured).
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
