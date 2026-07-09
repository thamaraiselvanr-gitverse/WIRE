"""Full-pipeline end-to-end test against a local file:// page.

Exercises the real ExecutionRouter.execute_pipeline path — crawl, Playwright
capture, asset localization, design analysis, CIDS synthesis, responsive/pseudo/
@keyframes capture, HTML/React/Vue compilation, semantic interpretation,
structural + visual fidelity, dynamic-region masking, template ecosystem, and
the .wire artifact — without any network access. Requires a Playwright browser
(installed in CI via `playwright install chromium`).
"""

import os

import pytest

from wire.orchestrator.execution_router import ExecutionRouter

FIXTURE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Acme Studio</title>
<style>
  :root { --brand: #2b6cb0; }
  body { font-family: Arial, sans-serif; margin:0; color:#222; background:#fff; }
  header.hero { background: #2b6cb0; color:#fff; padding:48px 24px; }
  header.hero h1 { font-size: 40px; }
  .cta { display:inline-block; background:#e0674f; color:#fff; padding:12px 20px; }
  .cta:hover { background:#c04a35; }
  .grid { display:grid; grid-template-columns: repeat(3,1fr); gap:24px; padding:32px; }
  .card { border:1px solid #ddd; border-radius:12px; padding:16px; }
  @media (max-width:600px){ .grid { grid-template-columns:1fr; } }
  @keyframes fade { from {opacity:0} to {opacity:1} }
</style></head>
<body>
  <header class="hero"><h1>Acme Studio</h1><p>We build things.</p>
    <a class="cta" href="#contact">Get started</a></header>
  <main><section class="grid">
    <div class="card"><h3>Design</h3><p>Beautiful interfaces.</p></div>
    <div class="card"><h3>Build</h3><p>Robust engineering.</p></div>
    <div class="card"><h3>Ship</h3><p>Fast delivery.</p></div>
  </section></main>
  <footer><p>Acme</p></footer>
</body></html>
"""


@pytest.mark.slow
@pytest.mark.asyncio
async def test_full_pipeline_against_local_file(tmp_path):
    site = tmp_path / "site.html"
    site.write_text(FIXTURE_HTML, encoding="utf-8")

    router = ExecutionRouter()
    router.storage.base_dir = str(tmp_path / "out")

    url = "file://" + str(site)
    score = await router.execute_pipeline(url)

    # A clean run must produce a bounded fidelity score.
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0

    run_dir = os.path.join(router.storage.base_dir, "site")
    assert os.path.isdir(run_dir)

    # Core deliverables must all be written.
    for name in [
        "index.html",
        "output_editable.html",
        "output_react.jsx",
        "output_vue.vue",
        "schema_cids.json",
        "design_architecture.json",
        "structural_validation.json",
        "structural_validation_clone.json",
        "visual_fidelity_report.json",
        "computed_styles.json",
        "dynamic_regions.json",
        "extraction_report.json",
        "website_form_schema.json",
        "compliance_report.json",
    ]:
        assert os.path.exists(os.path.join(run_dir, name)), f"missing {name}"

    # The editable HTML must be a full document that preserved the non-inline
    # styling (breakpoints, interaction states, animations).
    editable = (tmp_path / "out" / "site" / "output_editable.html").read_text(
        encoding="utf-8"
    )
    assert editable.lstrip().startswith("<!doctype html>")
    assert "@media" in editable
    assert ":hover" in editable
    assert "@keyframes" in editable

    # A verified .wire artifact should have been packaged.
    assert any(f.endswith(".wire") for f in os.listdir(run_dir))
