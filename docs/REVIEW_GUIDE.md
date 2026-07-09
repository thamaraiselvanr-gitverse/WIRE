# Reviewer's guide — Phases A–D branch

This PR is one branch (63 commits) that intentionally spans two themes. The
themes are interleaved at the file level (e.g. `execution_router.py` is touched
by 27 commits carrying *both* engine and platform changes), so they can't be
split into two independently-clean PRs without rewriting history. Instead,
**review it in two logical passes** using the allocation below.

Suggested order: **Pass 1 (engine)** first — it's the product core and the
platform layer sits on top of it — then **Pass 2 (platform)**. The shared
chores need only a skim.

---

## Pass 1 — Engine accuracy (38 commits)

**What it does:** turns reconstruction from "always ~100%" into an honestly
measured pipeline, and makes repurposing actually work and be scored.

**Where to focus review:**
- `wire/orchestrator/execution_router.py` — the pipeline; the engine changes
  here are style capture, SSIM wiring, slot discovery, interactivity, corpus.
- `wire/schema/canonical.py`, `schema/style_mapper.py` — CIDS + cascade denylist.
- `wire/agents/observation/computed_style_capturer.py` — browser-first styles,
  responsive + dark-mode deltas.
- `wire/validation/visual_diff.py` — SSIM + dynamic-region mask.
- `wire/semantic/slot_discovery.py`, `wire/evaluation/*` — offline repurposing
  + measurement (`repurpose_harness.py`, `layout_safety.py`, `corpus_runner.py`).
- `wire/agents/extraction/asset_downloader.py` — clone completeness (imports,
  srcset, fonts, manifests, dedup, charset, retry).
- `wire/compilers/*`, `wire/layout/interactivity_transformer.py`.

**Key questions:** Are the fidelity caps honest (no vacuous 100s)? Is the SSIM
math sound? Does slot discovery mutate the CIDS safely? Any asset-localization
edge case that could fetch or leak an unintended URL?

## Pass 2 — Platform hardening (16 commits)

**What it does:** wraps the engine in a production platform — auth, durable
queue, isolation, security, ops.

**Where to focus review:**
- `wire/api/auth.py`, `auth_routes.py` — JWT (no shared secret), scoped tokens,
  rotating refresh tokens, password policy.
- `wire/api/main_routes.py` — per-project run isolation, scoped file/stream
  tokens, CSP-sandboxed serving, cached router.
- `wire/api/main.py` — security-header middleware, latency histogram.
- `wire/api/rate_limit.py` — Redis-backed limiter (fails open) + in-proc fallback.
- `wire/api/job_queue.py`, `wire/worker.py` — durable queue, claim-token/
  heartbeat no-double-run guard.
- `wire/utils/url_guard.py` — SSRF guard (trust boundary + subresource).
- `migrations/`, `wire/api/models.py` — schema evolution.
- `deploy/`, `Dockerfile`, `.env.example`, `README.md` — ops.

**Key questions:** Any auth bypass in the scoped-token paths? Is run isolation
airtight (no cross-tenant artifact access)? Does the SSRF guard cover every
user-supplied URL? Are secrets kept out of the image/logs?

## Shared chores (9 commits) — skim only

Repo-wide Black/Ruff formatting, mypy-strict backlog to zero, coverage raised
to the 90% gate, `.gitignore`, and the initial `CLAUDE.md`. No behavior change;
low scrutiny.

---

## Merge blocker — CI gate fix (apply separately)

CI currently does **not** run mypy, the frontend tests are non-blocking, and
the workflow triggers on `main` while the default branch is `master` (so CI
would not fire on this PR at all). The fix to `.github/workflows/ci.yml` must
be committed by a maintainer with workflow scope:

```diff
 on:
   push:
-    branches: [ "main" ]
+    branches: [ "master", "main" ]
   pull_request:
-    branches: [ "main" ]
+    branches: [ "master", "main" ]
```
```diff
       - name: Install Linting Dependencies
         run: |
           pip install ruff black mypy
+          pip install -e ".[dev]"
       - name: Run Black
         run: black --check wire tests
       - name: Run Ruff
         run: ruff check wire tests
+      - name: Run Mypy
+        run: mypy wire
```
```diff
       - name: Run Vitest
-        run: npm run test:ci || echo "Tests pending" # we'll replace this once tests are fully constructed
+        run: npm run test:ci
```

## Local verification (this branch)

- Backend: 534 passed / 3 skipped, coverage 90.54% (gate 90%)
- Mypy strict: clean (107 files); Black + Ruff: clean
- Frontend: 8 Vitest tests passing; `tsc` clean

---

## Full commit allocation

### Engine accuracy (38)

| hash | subject |
| --- | --- |
| 597d399 | Wire real fidelity signals into scoring, widen CSS capture, add real crawling |
| c53db13 | Improve structural-diff accuracy and preserve @media responsive styling |
| b9b5850 | Capture :hover/:focus/:active CSS and richer design-token extraction |
| 2ef8314 | Adapter parity for responsive/pseudo styles + capture @font-face/@keyframes |
| 5834062 | Add full-document HTML compile and emit editable reconstruction as a deliverable |
| c715768 | Reconstruct wire/templates package to unblock Phase 6/8/9 |
| 7e88adb | Add brand-transfer: apply a brand palette onto a reconstructed layout |
| 78ba80b | Dead-code cleanup + real visual-diff dynamic-region masking |
| 910ef3a | Add multi-modal input ingestion: video, audio, and documents |
| 5079fe6 | Add comprehensive in-browser design-knowledge extraction |
| 27b57a6 | Add runtime behavioral capture (animation libs, state deltas, scroll reveals) |
| 0f5192e | Localize responsive images, media, and icons in the pixel-faithful clone |
| 5077ab7 | Turn stealth, auth, and scheduler stubs into real capabilities |
| 67e201d | Deduplicate repeated inline styles into shared classes in the HTML compiler |
| 1aea348 | Extract understanding from multimedia inputs and carry it into substitution |
| 54c9b09 | Fix external-CSS @font-face path parity in the editable output |
| 52ad773 | Extend inline-style deduplication to the React and Vue adapters |
| e416d1a | Migrate LLM client from google-generativeai to the google-genai SDK |
| 3a2fdc7 | Reconstruction accuracy: engine-computed styles + honest editable-output fidelity |
| 597676c | Extraction: follow and recursively localize @import CSS chains |
| f15d2ed | Accuracy: SSIM visual score + denylist-based style capture |
| 4f79d74 | Apply the dynamic-region mask to the SSIM score |
| 5664758 | Capture per-breakpoint computed styles for responsive states |
| 62ba9ff | Phase-0: honest end-to-end repurposing-success harness |
| aeaa413 | Phase-1: heuristic slot discovery so pages are repurposable without an LLM |
| 9fb46e9 | Phase-2: content-fit / layout-safety checks folded into repurpose score |
| 27c811c | Phase-3: restore JS-driven dropdowns and disclosures declaratively |
| 3e1f90d | Phase-3 follow-on: restore ARIA tabs and carousels declaratively |
| 489e54a | Phase-4: corpus evaluation runner + baseline success distribution |
| 3187661 | Clone completeness: <base href>, meta images, SVG sprites, url() safety |
| 95abc70 | Network resilience: retry with backoff + Retry-After for asset downloads |
| 3aac9ac | Clone edge cases: lazy-load scroll, charset normalization, asset dedup |
| 77f1b48 | Localize PWA manifest icons and preload/prefetch resource hints |
| 9c079b8 | Capture dark-mode (prefers-color-scheme) styles as media deltas |
| f44db4a | Docs: record lazy-scroll, dark-mode capture, dedup/charset in known state |
| abfefa0 | Opt-in tracker stripping with audit report |
| 4fa1d4c | Per-breakpoint visual validation: SSIM at 768/480 caps fidelity |
| 10ff8f6 | Regenerate corpus baseline with per-breakpoint SSIM evidence |

### Platform hardening (16)

| hash | subject |
| --- | --- |
| 6b72db7 | Wire brand-transfer + live editable preview into the dashboard |
| 0f0067d | Close the multi-modal loop: content submit endpoint, upload UI, doc-text in prompt |
| cc14240 | Redesign frontend UI to a clean LLM-assistant aesthetic |
| 2894ad2 | Harden for real users: remove shared JWT secret, add SSRF guard, configurable CORS |
| d4d5cd3 | Production hardening: sub-resource SSRF guard, rate limiting, Dockerfile |
| 53058cb | Make the frontend API base URL configurable (production readiness) |
| 3903094 | Add Alembic migrations and PostgreSQL support |
| f4b7a1d | Frontend: eliminate no-explicit-any and clean up lint |
| 9e3895e | Durable, DB-backed reconstruction job queue with a worker |
| 3443ef4 | Add observability: Prometheus metrics endpoint + optional Sentry |
| d480c80 | Enforce robots compliance and per-user daily reconstruction quota |
| b824b5c | Phase A security hardening: run isolation, scoped tokens, stream auth |
| 4418fbb | Phase B: Redis limits, refresh tokens, headers, claim guards, latency |
| 52b348e | Phase B5: real README, docker-compose stack, operations runbook |
| b3326b7 | Phase C: router caching, Dashboard a11y pass, frontend flow tests |
| 4e135f4 | Phase D: object-storage sync for run durability (S3-compatible) |

### Shared chores (9) — skim

| hash | subject |
| --- | --- |
| 62b0d69 | Add CLAUDE.md project context for Claude Code |
| 1e7ee60 | Format repo with Black and green the Ruff lint gate |
| e8b3b26 | Raise real test coverage (75% -> 86%) with an e2e pipeline test; fix CI test config |
| 7201a47 | Raise test coverage to 90% to satisfy the CI coverage gate |
| 4257ea0 | Reduce mypy strict backlog: annotations, third-party overrides (part 1) |
| 63cb07f | Clear the mypy strict backlog to zero |
| ad3afa1 | Format test_url_guard (black) |
| db44694 | Ignore corpus_output/ runtime evaluation artifacts |
| f9cd3b5 | Format: collapse ImageValue constructor to one line (black) |
