"""Phase-4 corpus aggregation + payload synthesis (pure, no browser)."""

import os

import pytest

from wire.evaluation.corpus_runner import (
    CorpusRunner,
    SiteResult,
    default_corpus,
    render_markdown,
)
from wire.schema.semantic_schema import (
    FormField,
    FormFieldType,
    SectionRole,
    WebsiteFormSchema,
)


def _site(success, ok=True, fidelity=50.0, safety=100.0, restored=0):
    return SiteResult(
        target="t",
        ok=ok,
        fidelity_score=fidelity,
        schema_field_count=3.0,
        repurpose_success=success,
        slot_fill_rate=100.0,
        layout_safety_score=safety,
        structural_score=90.0,
        interactive_restored=float(restored),
    )


def test_aggregate_distribution_and_buckets():
    results = [
        _site(100.0),
        _site(90.0),
        _site(40.0),
        _site(0.0, ok=False),  # failed run is excluded from stats
    ]
    report = CorpusRunner.aggregate(results)
    assert report.total == 4
    assert report.succeeded == 3
    assert report.failed == 1

    rs = report.metrics["repurpose_success"]
    assert rs.n == 3
    assert rs.min == 40.0
    assert rs.max == 100.0
    assert rs.median == 90.0
    # Buckets over the 3 succeeded sites.
    assert report.repurpose_success_buckets["96-100"] == 1
    assert report.repurpose_success_buckets["81-95"] == 1
    assert report.repurpose_success_buckets["1-50"] == 1


def test_aggregate_all_failed_has_no_metrics():
    report = CorpusRunner.aggregate([_site(0.0, ok=False)])
    assert report.succeeded == 0
    assert report.metrics == {}


def test_stats_percentiles():
    stats = CorpusRunner._stats([10.0, 20.0, 30.0, 40.0])
    assert stats is not None
    assert stats.n == 4
    assert stats.mean == 25.0
    assert stats.min == 10.0 and stats.max == 40.0


def test_auto_payload_fills_only_text_like_fields():
    schema = WebsiteFormSchema(
        source_url="https://ex.test",
        fields=[
            FormField(
                field_id="headline",
                slot_id="s1",
                cids_node_path="root > h1:nth-child(1)",
                label="Hero Heading",
                field_type=FormFieldType.TEXT,
                section_role=SectionRole.HERO,
            ),
            FormField(
                field_id="hero_img",
                slot_id="s2",
                cids_node_path="root > img:nth-child(2)",
                label="Hero Image",
                field_type=FormFieldType.IMAGE,
                section_role=SectionRole.HERO,
            ),
        ],
    )
    payload = CorpusRunner._auto_payload(schema)
    assert "headline" in payload.field_values
    assert "hero_img" not in payload.field_values  # image needs real upload
    assert payload.field_values["headline"].value == "Sample Hero Heading"


def test_render_markdown_has_table_and_buckets():
    report = CorpusRunner.aggregate([_site(100.0), _site(80.0)])
    md = render_markdown(report)
    assert "# WIRE corpus evaluation" in md
    assert "| metric | n | mean |" in md
    assert "repurpose_success" in md
    assert "Repurpose-success buckets" in md


def test_bundled_corpus_fixtures_exist():
    corpus = default_corpus()
    assert len(corpus) >= 5
    assert all(p.endswith(".html") and os.path.exists(p) for p in corpus)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_corpus_runner_end_to_end_on_two_fixtures(tmp_path):
    corpus = default_corpus()
    targets = [
        p
        for p in corpus
        if os.path.basename(p) in ("static_hero.html", "faq_accordion.html")
    ]
    runner = CorpusRunner(base_dir=str(tmp_path / "out"))
    report = await runner.run(targets)

    assert report.total == 2
    assert report.succeeded == 2
    # The static hero exposes text slots and repurposes; success is measured.
    assert "repurpose_success" in report.metrics
    assert report.metrics["schema_field_count"].max >= 1
    # The FAQ page restores its ARIA disclosures.
    assert report.metrics["interactive_restored"].max >= 1
