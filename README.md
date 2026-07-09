# WIRE — Semantic Web Reconstructor

WIRE takes a URL and produces two things from one crawl:

1. **A pixel-faithful clone** — the original HTML with every asset localized
   (images, CSS with nested `@import`/`url()` chains, fonts, icons, media,
   PWA manifests), deduplicated and charset-normalized.
2. **A semantic, editable version** — the page reduced to a canonical design
   schema (CIDS), with replaceable content discovered and bound to form
   fields, then recompiled to HTML / React / Vue. This is the product:
   **repurpose someone's layout with your own content without breaking it** —
   and every claim is measured (visual SSIM at desktop *and* mobile
   breakpoints, structural similarity, layout-safety checks on substituted
   content, a composite repurpose score with honesty guards).

The platform wraps that engine in a FastAPI backend (auth, projects, durable
job queue, quotas) and a React dashboard (previews, brand transfer, content
substitution).

## Quickstart (CLI, no server)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium

# Reconstruct a single URL into ./output/<domain>/
.venv/bin/python -m wire.main https://example.com
```

Key artifacts per run: `index.html` (clone), `output_editable.html` (editable
product), `output_interactive.html` (CSS-restored dropdowns/tabs/carousels),
`output_react.jsx` / `output_vue.vue`, `website_form_schema.json` (editable
fields), `fidelity` reports (`visual_fidelity_*.json`, `repurpose_report.json`).

## Running the platform

```bash
# API (terminal 1)
cp .env.example .env          # set JWT_SECRET_KEY at minimum
uvicorn wire.api.main:app --port 8000

# Reconstruction worker (terminal 2) — drains the durable job queue
.venv/bin/python -m wire.worker

# Frontend (terminal 3)
cd frontend && npm install && npm run dev    # http://localhost:5173
```

For a production-shaped stack (Postgres + Redis + API + worker + migrations)
see [`deploy/docker-compose.yml`](deploy/docker-compose.yml) and the
operations guide in [`deploy/RUNBOOK.md`](deploy/RUNBOOK.md).

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Required | Purpose |
| --- | --- | --- |
| `JWT_SECRET_KEY` | **prod** | JWT signing key (ephemeral random if unset — tokens die on restart) |
| `DATABASE_URL` | no | Async SQLAlchemy URL; SQLite file by default, `postgresql+asyncpg://…` in prod |
| `WIRE_REDIS_URL` | multi-proc | Shared rate limiting across API replicas (in-process fallback if unset) |
| `WIRE_CORS_ORIGINS` | prod | Comma-separated allowed browser origins |
| `WIRE_ENABLE_HSTS` | behind TLS | Emit `Strict-Transport-Security` |
| `GEMINI_API_KEY` | no | LLM semantic refinement; the pipeline is fully functional offline without it |
| `WIRE_ACCESS_TOKEN_MINUTES` / `WIRE_REFRESH_TOKEN_DAYS` | no | Session lifetimes (60 min / 14 days) |
| `WIRE_RATE_LIMIT_RECONSTRUCTIONS` / `WIRE_RATE_LIMIT_AUTH` | no | Per-minute budgets (10 / 20) |
| `WIRE_DAILY_RECONSTRUCTION_QUOTA` | no | Per-user daily cap (50) |
| `SENTRY_DSN` | no | Error reporting |

## Development

```bash
.venv/bin/python -m pytest tests/ -q --cov=wire --cov-fail-under=90
.venv/bin/black wire tests && .venv/bin/ruff check wire tests && .venv/bin/mypy wire
.venv/bin/python -m wire.evaluation.corpus_runner   # measured success over fixture corpus
```

Engineering conventions, verified pipeline internals, and known gaps are
documented in [`CLAUDE.md`](CLAUDE.md); the committed evaluation baseline is
[`wire/evaluation/CORPUS_BASELINE.md`](wire/evaluation/CORPUS_BASELINE.md).

## Compliance

Reconstruction respects `robots.txt` by default (`respect_robots`), strips
nothing unless asked (tracker stripping is opt-in), and SSRF-guards every
user-supplied URL and page subresource. Cloning third-party sites can involve
copyrighted material — use against sites you have the right to reproduce.
