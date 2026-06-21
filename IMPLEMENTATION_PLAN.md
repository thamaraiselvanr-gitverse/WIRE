# WIRE — Semantic Web Reconstructor
## Implementation Plan v2.3 — FINAL

---

## 1. Mission Statement

WIRE is a platform-centric, abstraction-driven design intelligence system for deterministic extraction, reconstruction, and regeneration of web interfaces, exposed through a unified user interface and modular service architecture. The system enforces a schema-driven data contract with deterministic slot binding and validated multi-modal content injection, enabling precise placement of user-provided text, images, audio, video, and embedded media while preserving original layout structure, interaction behavior, and visual fidelity. All inputs are subject to triple validation across format, media compatibility, and layout constraints, with threshold-based violation gates preventing structural degradation. Output integrity is guaranteed through fidelity scoring, explicit degradation states, and structured audit reporting, ensuring full traceability, auditability, and reproducibility. WIRE includes a complete template ecosystem with indexed storage, semantic retrieval, versioned and cryptographically verifiable template artifacts, component-level composition, design token abstraction, and instant preview rendering. The platform supports multi-user access, project-based workflows, real-time previews, cloud-backed storage, and extensible APIs. A resilient connectivity layer ensures fault-tolerant communication, automatic recovery, and zero data loss. Built on scalable orchestration and abstraction layers, WIRE enables seamless integration of future frameworks, distributed processing, AI-driven querying, and enterprise-grade deployment without modification to core system logic.

---

## 2. Architectural Foundation

> [!IMPORTANT]
> **FINAL ELITE CONSOLIDATED BLOCK — All architectural decisions are locked.**

WIRE is implemented as a **distributed-first, abstraction-driven system** with a **canonical design schema** at its core. Execution begins in a single-node environment that simulates distributed behavior, ensuring seamless scalability. The system follows a **phased activation strategy**, where a fully defined architecture is incrementally realized through a functional pipeline. Existing modules are refactored into structured layers, enabling support for full-spectrum web application complexity. Storage is implemented through a **hybrid abstraction model**, allowing transparent transition from local execution to scalable production infrastructure.

### 2.1 Six Architectural Pillars

| # | Pillar | Decision |
|---|--------|----------|
| 1 | **Runtime Model** | Distributed-first with single-node initial execution. Redis-backed coordination, NUMA-aware scheduling, and consensus validation preserved as abstraction layers — no architectural change needed for multi-node deployment. |
| 2 | **Output Schema** | Canonical Intermediate Design Schema (CIDS) as single source of truth. HTML/CSS/JS compiler validates first; React/Vue compilers are independent adapter plugins consuming the same schema. |
| 3 | **Module Strategy** | Audit-driven augmentation. Existing modules are analyzed, validated, and refactored into standardized layers through defined interfaces. No redundant rewrites. |
| 4 | **Site Complexity** | Full-spectrum support: static sites, SPAs, authenticated environments, dynamically hydrated systems. Progressive capability activation based on runtime site complexity detection. |
| 5 | **Delivery Model** | Phased activation. Full blueprint defined upfront; subsystems incrementally implemented and validated through a functional end-to-end pipeline. |
| 6 | **Storage Backend** | Hybrid abstraction: JSON + SQLite locally, with transparent compatibility for PostgreSQL, object storage, and vector databases in production. |

### 2.2 Implementation Decisions

| # | Decision | Specification |
|---|----------|---------------|
| 7 | **Browser Engine** | Playwright (Python-native) — multi-browser support, robust async control, superior modern web app handling. |
| 8 | **Python Version** | Python 3.11 minimum — leverages `TaskGroup`, advanced typing, modern async features. |
| 9 | **Authentication** | Dual-mode: manual session injection + automated login flows, with progressive activation based on site complexity. |
| 10 | **Stealth Layer** | Advanced — browser fingerprint normalization, request throttling, proxy abstraction, extensible to full enterprise-grade anti-detection. |
| 11 | **Interface** | CLI-first (Phase 1) with service layer abstraction enabling seamless FastAPI REST API integration in subsequent phases. |
| 12 | **Validation Target** | AVS Engineering College — `https://www.avsenggcollege.ac.in/` — controlled, semi-static real-world site for deterministic Phase 1 validation. |

### 2.4 Execution Behavior

| # | Decision | Specification |
|---|----------|---------------|
| 19 | **Error Model** | Conditionally resilient execution with explicit error classification. Non-critical failures tolerated under controlled degradation; critical failures (core CSS loss, layout integrity, DOM completeness) trigger deterministic termination. All deviations quantified through a fidelity scoring system with structured error reporting. |
| 20 | **Validation URL** | `https://www.avsenggcollege.ac.in/` — hard-coded Phase 1 golden reference target. |

### 2.5 Operational Environment

> [!IMPORTANT]
> **DEVELOPMENT DOCTRINE**
> WIRE uses a project-scoped virtual environment (.venv) with fully version-pinned dependencies to ensure reproducible environments. The system exposes a standardized CLI via pyproject.toml, enabling execution through `wire <command>` with `python -m wire` as a development fallback. Environment setup follows an explicit initialization sequence, including dependency installation and manual Playwright browser provisioning (`playwright install`), ensuring transparent, controlled, and deterministic system configuration.
> 
> WIRE enforces enterprise-grade development standards from inception, integrating automated formatting (Black), linting (Ruff), and strict static type checking (Mypy) via a centralized pyproject.toml configuration, with enforcement through pre-commit hooks and CI validation. Version control is initialized at project start with a structured Git workflow and comprehensive .gitignore, guaranteeing deterministic code quality, full traceability, and safe, incremental system evolution.
> 
> WIRE standardizes on uv for dependency and environment management, enforcing lockfile-based version pinning to guarantee deterministic, reproducible builds across all environments. Structured logging is implemented using structlog, producing consistent, JSON-based, context-rich logs across all system layers with integrated context propagation and trace identifiers. This ensures full observability, auditability, and debuggability of system behavior, aligning with enterprise-grade reliability and monitoring standards.
> 
> WIRE enforces a comprehensive quality assurance framework using pytest with pytest-asyncio for asynchronous test execution and pytest-cov for coverage analysis, with CI enforcing a minimum 90% coverage threshold and mandatory coverage for all critical modules. Continuous integration is established from inception, executing automated pipelines on every commit to validate automated dependency resolution, formatting, linting, type safety, and test integrity, with failure conditions blocking code integration. Documentation standards mandate Google-style docstrings combined with strict type annotations, ensuring consistent, self-describing APIs across all service and core layers. Together, these mechanisms guarantee deterministic behavior, maintainability, and enterprise-grade reliability.
> 
> WIRE enforces enterprise-grade deployment and operational standards through fully containerized execution using Docker, with isolated Playwright environments and versioned container images to guarantee deterministic, reproducible behavior across all infrastructures. Security is integrated into the CI/CD pipeline via automated dependency vulnerability scanning, static code analysis, and strict environment configuration management using validated .env schemas. Version control follows Conventional Commits enforced through automated hooks, enabling semantic versioning, automated changelog generation, and deterministic release workflows. All build and deployment processes are validated in CI, ensuring secure, consistent, and immutable artifacts for scalable, production-grade deployments.

### 2.3 Template Ecosystem Architecture

> [!IMPORTANT]
> **TEMPLATE ECOSYSTEM ELITE BLOCK — All template decisions are locked.**

WIRE will implement a fully indexed and versioned template ecosystem, combining relational and vector-based retrieval, independent design token systems, cryptographically verifiable template artifacts, and component-level composition capabilities. The system ensures scalable discovery, deterministic reuse, and cross-template interoperability through strict schema contracts and dependency-aware architecture.

| # | Decision | Specification |
|---|----------|---------------|
| 13 | **Template Registry** | Fully indexed, queryable registry with structured metadata, semantic tagging, and ranking — backed by hybrid relational + vector indexing. |
| 14 | **Design Token System** | Normalized, versioned tokens with cross-template referencing — enabling consistent reuse and independent evolution of visual systems. |
| 15 | **Artifact Format** | Versioned, cryptographically verifiable `.wire` format — integrity validation, dependency resolution, cross-environment portability. |
| 16 | **Component Composition** | Component-level abstraction with identity tracking — deterministic composition through structural compatibility validation. |
| 17 | **Template Versioning** | Delta-based version control — efficient storage, historical comparison, and rollback of structural and visual changes. |
| 18 | **Template Preview** | Lightweight, sandboxed preview rendering with caching — instant visualization without full pipeline execution. |

---

## 3. Output Specification — The 13 Deliverables

When fully operational, WIRE produces the following from a single URL input:

### Tier 1 — Core Deliverables (Phases 1–3)
| # | Deliverable | Description |
|---|-------------|-------------|
| 1 | **Production-Ready Codebase** | Clean HTML/CSS/JS files that perfectly replicate the target site with all assets localized |
| 2 | **Structured Input Blueprint** | Schema-driven slot binding system ensuring deterministic placement into predefined layout slots. All inputs undergo triple validation—format, media compatibility, and layout constraints—with explicit fallback handling for missing or incompatible data. Constraint violations evaluated against defined thresholds to prevent structural degradation, guaranteeing design integrity and output fidelity. All transformations, validations, and fallback decisions recorded through structured reporting for full traceability, auditability, and reproducibility. |
| 3 | **Design Architecture Report** | Extracted color palettes, typography scales, spacing systems, component hierarchy |
| 4 | **Multi-Viewport Renders** | Desktop, tablet, and mobile captures with breakpoint analysis |
| 5 | **Full Domain Site Map** | Complete page index with navigation graph and route hierarchy |

### Tier 2 — Advanced Deliverables (Phases 4–5)
| # | Deliverable | Description |
|---|-------------|-------------|
| 6 | **Queryable Design Knowledge Index** | Structured database of the site's design architecture — queryable by component, property, or pattern |
| 7 | **Interaction State Catalogue** | Every hover, click, scroll, and animation state documented with visual evidence |
| 8 | **AI Design Prompts** | LLM-ready prompts extracted from the design for regeneration or variation |
| 9 | **Visual Fidelity Hash & Diff Report** | Perceptual hash fingerprints comparing original vs reconstruction with pixel-level diff |
| 10 | **Compliance/Legal Report** | robots.txt analysis, ToS detection, safe-to-reconstruct classification |
| 11 | **Resumable Checkpoint State** | Progress state files enabling mid-crawl resume without data loss |
| 12 | **Template Repository Entry** | Cached site template for instant reuse without re-crawling |
| 13 | **Multi-Region Render Variants** | Geo-aware captures showing CDN/region-specific content differences |

---

## 4. Component Architecture — Layer Matrix

### Layer 1: Distributed Orchestrator
*Manages execution routing, scheduling, coordination, and fault tolerance.*

| File | Purpose | Phase |
|------|---------|-------|
| `wire/orchestrator/__init__.py` | Layer initialization and public API | 1 |
| `wire/orchestrator/execution_router.py` | Routes tasks to available execution slots, manages pipeline sequencing | 1 |
| `wire/orchestrator/scheduler.py` | NUMA-aware task scheduling with single-node simulation and multi-node abstraction | 2 |
| `wire/orchestrator/coordinator.py` | Redis-compatible coordination (local in-memory lock manager for single-node) | 2 |
| `wire/orchestrator/checkpointing.py` | TCP-style checkpointing for resumable crawls | 3 |
| `wire/orchestrator/semantic_merger.py` | Merges partial results from parallel workers into coherent output | 3 |
| `wire/orchestrator/consensus.py` | Quorum-based validation for reconstruction fidelity (single-node simulated) | 5 |

---

### Layer 2: Exploration & Fuzzing
*Autonomous domain discovery, sitemap generation, and interaction state enumeration.*

| File | Purpose | Phase |
|------|---------|-------|
| `wire/agents/exploration/__init__.py` | Layer initialization | 1 |
| `wire/agents/exploration/crawler.py` | Full-domain async crawling with sitemap generation, respects robots.txt | 1 |
| `wire/agents/exploration/fuzzer.py` | Interaction fuzzing — discovers all clickable/hoverable/scrollable elements | 3 |
| `wire/agents/exploration/region_probe.py` | Multi-region rendering via proxy/geo-rotation | 5 |

---

### Layer 3: Deep Observation
*Playwright-powered browser rendering, viewport capture, Shadow DOM piercing, SPA detection.*

| File | Purpose | Phase |
|------|---------|-------|
| `wire/agents/observation/__init__.py` | Layer initialization | 1 |
| `wire/agents/observation/browser_session.py` | Playwright-based headless browser session management with async context control | 1 |
| `wire/agents/observation/stealth.py` | Browser fingerprint normalization, request throttling, proxy abstraction | 1 |
| `wire/agents/observation/viewport_renderer.py` | Multi-viewport capture (desktop/tablet/mobile) with breakpoint detection | 2 |
| `wire/agents/observation/auth_handler.py` | Dual-mode authentication: manual session injection + automated login flows | 2 |
| `wire/agents/observation/shadow_piercer.py` | Shadow DOM and Web Component content extraction | 4 |
| `wire/agents/observation/spa_detector.py` | SPA/SSR/hydration detection and appropriate rendering strategy selection | 4 |

---

### Layer 4: Extraction & Compliance
*Design analysis, asset downloading, legal detection, network monitoring.*

| File | Purpose | Phase |
|------|---------|-------|
| `wire/agents/extraction/__init__.py` | Layer initialization | 1 |
| `wire/agents/extraction/asset_downloader.py` | Recursive CSS/JS/image/font download with local path rewriting | 1 |
| `wire/agents/extraction/design_analyzer.py` | Extracts color palettes, typography, spacing, component hierarchy | 2 |
| `wire/agents/extraction/interaction_recorder.py` | Records hover/click/scroll states as visual + CSS snapshots | 3 |
| `wire/agents/extraction/legal_detector.py` | robots.txt, ToS detection, compliance classification | 3 |
| `wire/agents/extraction/network_monitor.py` | Request interception, API endpoint discovery, dynamic data detection | 4 |

---

### Layer 5: Schema, Synthesis & Compilation
*Canonical schema generation, input blueprints, code compilation, AI prompt extraction.*

| File | Purpose | Phase |
|------|---------|-------|
| `wire/schema/__init__.py` | Layer initialization | 2 |
| `wire/schema/canonical.py` | **Canonical Intermediate Design Schema (CIDS)** — the single source of truth | 2 |
| `wire/schema/input_blueprint.py` | Schema-driven Data Contract generator — slot binding, triple validation (format/media/layout), threshold-based violation evaluation, fallback handling, and structured audit reporting for reproducible regeneration | 2 |
| `wire/compilers/__init__.py` | Compiler registry and adapter interface | 2 |
| `wire/compilers/html_compiler.py` | **Primary compiler** — CIDS → production HTML/CSS/JS | 2 |
| `wire/compilers/react_adapter.py` | CIDS → React components (independent adapter) | 5 |
| `wire/compilers/vue_adapter.py` | CIDS → Vue components (independent adapter) | 5 |
| `wire/synthesis/prompt_generator.py` | AI-ready design prompt extraction from CIDS | 4 |
| `wire/synthesis/knowledge_index.py` | Queryable design knowledge database | 4 |

---

### Layer 6: Storage, Validation & Infrastructure
*Hybrid storage abstraction, visual validation, template caching, service layer.*

| File | Purpose | Phase |
|------|---------|-------|
| `wire/storage/__init__.py` | Storage abstraction layer initialization | 1 |
| `wire/storage/backend.py` | Abstract storage interface (local JSON/SQLite ↔ Postgres/S3/Vector DB) | 1 |
| `wire/storage/local.py` | JSON + SQLite local implementation | 1 |
| `wire/storage/template_repo.py` | Template repository for cached reconstructions | 3 |
| `wire/validation/__init__.py` | Validation layer initialization | 3 |
| `wire/validation/visual_diff.py` | Perceptual hashing and pixel-level diff between original and reconstruction | 3 |
| `wire/validation/structural.py` | DOM structure comparison and semantic equivalence checking | 3 |
| `wire/utils/config.py` | Central configuration management | 1 |
| `wire/utils/logging.py` | Structured logging across all layers | 1 |
| `wire/main.py` | CLI entry point and pipeline orchestration | 1 |
| `wire/service.py` | Service layer abstraction — decouples pipeline logic from CLI, enables future FastAPI integration | 1 |
| `wire/utils/fidelity_scorer.py` | Fidelity scoring system — quantifies reconstruction accuracy, classifies errors (critical vs non-critical), enforces degradation states | 1 |

---

### Layer 7: Template Ecosystem
*Indexed registry, design tokens, component composition, versioning, and preview.*

| File | Purpose | Phase |
|------|---------|-------|
| `wire/templates/__init__.py` | Template ecosystem initialization | 6 |
| `wire/templates/registry.py` | Queryable template registry with semantic tagging, relational + vector indexing | 6 |
| `wire/templates/tokens.py` | Normalized, versioned design token system with cross-template referencing | 6 |
| `wire/templates/artifact.py` | Cryptographically verifiable `.wire` artifact format — packaging, signing, validation | 6 |
| `wire/templates/composer.py` | Component-level composition with identity tracking and structural compatibility checks | 6 |
| `wire/templates/versioning.py` | Delta-based version control for templates — diff, compare, rollback | 6 |
| `wire/templates/preview.py` | Sandboxed preview rendering with caching for instant template visualization | 6 |

---

## 5. Implementation Phases

### Phase 1 — Foundation Pipeline *(End-to-End MVP)*
**Goal:** URL → working local clone (single page)

**Deliverables unlocked:** #1 (Production Codebase), #5 (Site Map — single page)

**Tech stack:** Python 3.11+, Playwright, async/await with `TaskGroup`

```
URL Input → Crawler (single page) → Browser Session (Playwright + Stealth) → Asset Downloader → Local Storage → HTML Output
```

**Files:**
- `wire/main.py`, `wire/service.py`, `wire/utils/config.py`, `wire/utils/logging.py`, `wire/utils/fidelity_scorer.py`
- `wire/orchestrator/__init__.py`, `wire/orchestrator/execution_router.py`
- `wire/agents/exploration/__init__.py`, `wire/agents/exploration/crawler.py`
- `wire/agents/observation/__init__.py`, `wire/agents/observation/browser_session.py`, `wire/agents/observation/stealth.py`
- `wire/agents/extraction/__init__.py`, `wire/agents/extraction/asset_downloader.py`
- `wire/storage/__init__.py`, `wire/storage/backend.py`, `wire/storage/local.py`
- `pyproject.toml`, `requirements.txt`

**Validation Target:** `https://www.avsenggcollege.ac.in/`

**Verification:** Input `https://www.avsenggcollege.ac.in/` → output directory contains `index.html` + `assets/` → opens in browser and visually matches original. Fidelity score ≥ 90%.

---

### Phase 2 — Canonical Schema & Design Intelligence
**Goal:** Extract design architecture, generate CIDS, produce Data Contract, enable authenticated site access

**Deliverables unlocked:** #2 (Input Blueprint), #3 (Design Report), #4 (Multi-Viewport)

**Files:**
- `wire/schema/canonical.py`, `wire/schema/input_blueprint.py`
- `wire/compilers/__init__.py`, `wire/compilers/html_compiler.py`
- `wire/agents/extraction/design_analyzer.py`
- `wire/agents/observation/viewport_renderer.py`, `wire/agents/observation/auth_handler.py`
- `wire/orchestrator/scheduler.py`, `wire/orchestrator/coordinator.py`

**Verification:** CIDS schema validates against JSON Schema. HTML compiler output matches direct clone. Data Contract is machine-readable and human-fillable. Auth handler supports manual cookie injection.

---

### Phase 3 — Resilience, Validation & Interaction
**Goal:** Add checkpointing, visual validation, interaction fuzzing, compliance

**Deliverables unlocked:** #7 (Interaction Catalogue), #9 (Visual Diff), #10 (Compliance), #11 (Checkpoints), #12 (Template Repo)

**Files:**
- `wire/orchestrator/checkpointing.py`, `wire/orchestrator/semantic_merger.py`
- `wire/agents/exploration/fuzzer.py`
- `wire/agents/extraction/interaction_recorder.py`, `wire/agents/extraction/legal_detector.py`
- `wire/validation/visual_diff.py`, `wire/validation/structural.py`
- `wire/storage/template_repo.py`

**Verification:** Interrupt a crawl → resume → same output. Visual diff score > 95%. Interaction states catalogued with screenshots.

---

### Phase 4 — Full-Spectrum & Knowledge Engine
**Goal:** SPA support, Shadow DOM, knowledge index, AI prompts, network monitoring

**Deliverables unlocked:** #6 (Knowledge Index), #8 (AI Prompts)

**Files:**
- `wire/agents/observation/shadow_piercer.py`, `wire/agents/observation/spa_detector.py`
- `wire/agents/extraction/network_monitor.py`
- `wire/synthesis/prompt_generator.py`, `wire/synthesis/knowledge_index.py`

**Verification:** Successfully reconstruct a React SPA. Knowledge index returns accurate queries. AI prompts generate visually similar layouts when fed to an LLM.

---

### Phase 5 — Distributed Scale & Framework Adapters
**Goal:** Multi-region, consensus validation, React/Vue compilers

**Deliverables unlocked:** #13 (Multi-Region), plus React/Vue output formats

**Files:**
- `wire/agents/exploration/region_probe.py`
- `wire/orchestrator/consensus.py`
- `wire/compilers/react_adapter.py`, `wire/compilers/vue_adapter.py`

**Verification:** Multi-node simulation produces identical results to single-node. React/Vue output compiles and renders correctly.

---

### Phase 6 — Template Ecosystem
**Goal:** Full template lifecycle — registry, tokens, composition, versioning, preview

**Deliverables unlocked:** Template Library Management, Design Token Library, Component Composition, Template Versioning, Template Preview

**Files:**
- `wire/templates/__init__.py`, `wire/templates/registry.py`
- `wire/templates/tokens.py`, `wire/templates/artifact.py`
- `wire/templates/composer.py`, `wire/templates/versioning.py`
- `wire/templates/preview.py`

**Verification:**
- Registry indexes, tags, and retrieves templates by semantic query
- Design tokens apply cross-template (Site A's palette on Site B's layout)
- `.wire` artifact passes cryptographic integrity check after export/import
- Component composition produces structurally valid output from mixed sources
- Version diff correctly identifies structural and visual deltas
- Preview renders in < 2 seconds without full pipeline

---

## 6. Directory Structure

```
WIRE/
├── wire/
│   ├── __init__.py
│   ├── main.py                          # CLI entry point
│   ├── service.py                       # Service layer abstraction
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── execution_router.py
│   │   ├── scheduler.py
│   │   ├── coordinator.py
│   │   ├── checkpointing.py
│   │   ├── semantic_merger.py
│   │   └── consensus.py
│   ├── agents/
│   │   ├── exploration/
│   │   │   ├── __init__.py
│   │   │   ├── crawler.py
│   │   │   ├── fuzzer.py
│   │   │   └── region_probe.py
│   │   ├── observation/
│   │   │   ├── __init__.py
│   │   │   ├── browser_session.py       # Playwright-based
│   │   │   ├── stealth.py               # Fingerprint normalization
│   │   │   ├── auth_handler.py          # Dual-mode authentication
│   │   │   ├── viewport_renderer.py
│   │   │   ├── shadow_piercer.py
│   │   │   └── spa_detector.py
│   │   └── extraction/
│   │       ├── __init__.py
│   │       ├── asset_downloader.py
│   │       ├── design_analyzer.py
│   │       ├── interaction_recorder.py
│   │       ├── legal_detector.py
│   │       └── network_monitor.py
│   ├── schema/
│   │   ├── __init__.py
│   │   ├── canonical.py
│   │   └── input_blueprint.py
│   ├── compilers/
│   │   ├── __init__.py
│   │   ├── html_compiler.py
│   │   ├── react_adapter.py
│   │   └── vue_adapter.py
│   ├── synthesis/
│   │   ├── __init__.py
│   │   ├── prompt_generator.py
│   │   └── knowledge_index.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── backend.py
│   │   ├── local.py
│   │   └── template_repo.py
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── visual_diff.py
│   │   └── structural.py
│   ├── templates/
│   │   ├── __init__.py
│   │   ├── registry.py              # Indexed template library
│   │   ├── tokens.py                # Design token system
│   │   ├── artifact.py              # .wire format & crypto verification
│   │   ├── composer.py              # Component composition engine
│   │   ├── versioning.py            # Delta-based version control
│   │   └── preview.py               # Sandboxed preview renderer
│   └── utils/
│       ├── config.py
│       ├── logging.py
│       └── fidelity_scorer.py       # Reconstruction accuracy scoring
├── tests/
│   ├── unit/
│   ├── integration/
│   └── adversarial/
├── deploy/
├── output/                              # Generated reconstructions
├── requirements.txt
├── pyproject.toml
└── README.md
```

**Total files: 51** (45 Python modules + 5 project files + 1 template format spec)

---

## 7. Verification Plan

### Automated Tests
- **Unit tests** per module using `pytest` (Python 3.11+)
- **Integration test:** Full pipeline run against `https://www.avsenggcollege.ac.in/` → compare output against golden reference
- **Visual regression:** Perceptual hash comparison with configurable threshold (target: >95% fidelity)
- **Fidelity scoring:** Reconstruction must achieve ≥ 90% fidelity score with zero critical errors
- **Schema validation:** CIDS output validates against JSON Schema definition
- **Stealth validation:** Playwright sessions pass bot-detection checks
- **Error classification:** Verify critical errors trigger termination, non-critical errors produce structured warnings

### Manual Verification
- Browser-side visual inspection of reconstructed `https://www.avsenggcollege.ac.in/`
- Fidelity report review — confirm scoring reflects actual visual accuracy
- Data Contract fill-and-regenerate workflow test
- Interrupt/resume checkpoint test on multi-page crawl
- Auth handler test with manual cookie injection on a login-protected page

---

> [!IMPORTANT]
> **Status: ARCHITECTURE FULLY LOCKED** — All 20 decisions (6 pillars + 6 implementation specs + 6 template ecosystem + 2 execution behavior) are integrated. 51 files across 6 phases. Awaiting approval to begin Phase 1 execution.
