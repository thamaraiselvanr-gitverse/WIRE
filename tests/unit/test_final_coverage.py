"""Final coverage batch: CascadeResolver cascade capture, IntentReconciler
no-op/failed paths, and ExecutionRouter post-run guards for missing runs."""

import pytest

from wire.orchestrator.execution_router import ExecutionRouter
from wire.schema.style_mapper import CascadeResolver


def test_cascade_resolver_captures_pseudo_media_and_global():
    html = """<html><body>
      <a class="cta" href="#">Go</a>
      <div class="card">x</div>
    </body></html>"""
    css = """
      :root { --brand: #2b6cb0; }
      .cta { color: #fff; background: #e0674f; }
      .cta:hover { background: #c04a35; }
      .cta::before { content: ''; }
      .card, .cta { padding: 8px; }
      @media (max-width: 600px) { .card { padding: 4px; } }
      @font-face { font-family: 'Brand'; src: url('brand.woff2'); }
      @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
    """
    resolver = CascadeResolver()
    soup, styles_map = resolver.resolve(html, css)

    # Base declarations mapped onto elements.
    assert any("color" in props or "padding" in props for props in styles_map.values())
    # :hover captured into the pseudo map.
    assert any(":hover" in states for states in resolver.pseudo_map.values())
    # @media captured into the responsive map.
    assert any(resolver.responsive_map.values())
    # @font-face / @keyframes captured verbatim as global rules.
    joined = "\n".join(resolver.global_styles)
    assert "@font-face" in joined and "@keyframes" in joined


def test_intent_reconciler_noop_and_failed_extraction():
    from wire.schema.semantic_schema import WebsiteFormSchema
    from wire.semantic.intent_reconciler import IntentReconciler
    from wire.semantic.llm_guard import LLMGuard

    schema = WebsiteFormSchema(source_url="http://x", fields=[])
    rec = IntentReconciler(LLMGuard())  # no LLM client -> extraction fails

    # Empty intent -> unchanged.
    assert rec.reconcile(schema, None) is schema
    assert rec.reconcile(schema, "   ") is schema

    # Non-empty intent with no LLM -> heuristic extraction + application path.
    out = rec.reconcile(schema, "Emphasize the portfolio and exclude the team")
    assert isinstance(out, WebsiteFormSchema)


def test_router_post_run_guards_raise_for_missing_run(tmp_path):
    from wire.schema.submission_schema import SubmissionPayload

    router = ExecutionRouter()
    router.storage.base_dir = str(tmp_path / "out")

    with pytest.raises(ValueError):
        router.apply_brand("no_such_run", {"colors": {"primary": "#000"}})
    with pytest.raises(ValueError):
        router.remove_sections("no_such_run", ["root > section:nth-child(1)"])
    with pytest.raises(ValueError):
        router.generate_transformation_prompt(
            "no_such_run", SubmissionPayload(run_id="no_such_run", field_values={})
        )
