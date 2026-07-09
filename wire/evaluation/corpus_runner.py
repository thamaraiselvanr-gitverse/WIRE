"""Phase-4 corpus evaluation — run the whole stack over many sites and publish
a success distribution.

Phases 0-3 built honest per-run signals (fidelity, slot discovery, repurpose
success, layout safety, restored interactivity). One run tells you about one
page; it does not tell you how WIRE performs *in general*. This runner drives
the full pipeline + an auto-generated content payload + the repurpose harness
across a list of targets (bundled fixture archetypes, or live URLs when egress
allows), collects each site's metrics, and aggregates them into a distribution —
so "how well does WIRE actually work?" becomes a table of numbers, not a vibe.

Run it:  ``python -m wire.evaluation.corpus_runner [targets...]``
(no targets → the bundled ``tests/fixtures/corpus`` archetypes).
"""

import asyncio
import json
import os
import statistics
import sys
from typing import Dict, List, Optional

import structlog
from pydantic import BaseModel, Field

from wire.evaluation.repurpose_harness import RepurposeReport
from wire.schema.semantic_schema import FormFieldType, WebsiteFormSchema
from wire.schema.submission_schema import SubmissionPayload, TextValue

logger = structlog.get_logger(__name__)

# Metrics aggregated across the corpus (attribute name on SiteResult).
_METRICS = [
    "fidelity_score",
    "schema_field_count",
    "repurpose_success",
    "slot_fill_rate",
    "layout_safety_score",
    "structural_score",
    "interactive_restored",
]


class SiteResult(BaseModel):
    """Per-target outcome of a full pipeline + repurpose evaluation."""

    target: str
    ok: bool = False
    error: str = ""
    fidelity_score: Optional[float] = None
    schema_field_count: Optional[float] = None
    repurpose_success: Optional[float] = None
    slot_fill_rate: Optional[float] = None
    layout_safety_score: Optional[float] = None
    structural_score: Optional[float] = None
    interactive_restored: Optional[float] = None


class MetricStats(BaseModel):
    """Distribution summary for one metric across the corpus."""

    n: int
    mean: float
    median: float
    min: float
    max: float
    p25: float
    p75: float


class CorpusReport(BaseModel):
    """Aggregate distribution over an evaluated corpus."""

    total: int
    succeeded: int
    failed: int
    metrics: Dict[str, MetricStats] = Field(default_factory=dict)
    repurpose_success_buckets: Dict[str, int] = Field(default_factory=dict)
    sites: List[SiteResult] = Field(default_factory=list)


class CorpusRunner:
    """Drive the pipeline + repurpose harness across a set of targets."""

    def __init__(self, base_dir: str = "corpus_output") -> None:
        self.base_dir = base_dir

    async def run(self, targets: List[str]) -> CorpusReport:
        results: List[SiteResult] = []
        for target in targets:
            logger.info("corpus_target_started", target=target)
            results.append(await self.evaluate_target(target))
        report = self.aggregate(results)
        logger.info(
            "corpus_complete",
            total=report.total,
            succeeded=report.succeeded,
            failed=report.failed,
        )
        return report

    async def evaluate_target(self, target: str) -> SiteResult:
        # Imported lazily: pulls in Playwright and the whole pipeline graph.
        from wire.orchestrator.execution_router import ExecutionRouter

        url = target if "://" in target else "file://" + os.path.abspath(target)
        router = ExecutionRouter()
        router.storage.base_dir = self.base_dir
        try:
            fidelity = await router.execute_pipeline(url)
            run_dir = router.storage.current_run_dir
            run_id = os.path.basename(run_dir)

            form_schema = self._load_form_schema(run_dir)
            payload = self._auto_payload(form_schema)
            report: RepurposeReport = router.evaluate_repurpose(run_id, payload)

            return SiteResult(
                target=target,
                ok=True,
                fidelity_score=fidelity,
                schema_field_count=float(len(form_schema.fields)),
                repurpose_success=report.success_percent,
                slot_fill_rate=round(report.slot_fill_rate * 100.0, 2),
                layout_safety_score=report.layout_safety_score,
                structural_score=report.structural_score,
                interactive_restored=float(self._interactive_count(run_dir)),
            )
        except Exception as e:  # pragma: no cover - defensive per-site guard
            logger.warning("corpus_target_failed", target=target, error=str(e))
            return SiteResult(target=target, ok=False, error=str(e))

    # ── payload synthesis ────────────────────────────────────────────────────
    @staticmethod
    def _auto_payload(form_schema: WebsiteFormSchema) -> SubmissionPayload:
        """A happy-path payload: fill every text-like field with modest content
        (sized so the baseline exercises fit, not overflow)."""
        values: Dict[str, object] = {}
        for field in form_schema.fields:
            if field.field_type in (
                FormFieldType.TEXT,
                FormFieldType.TEXTAREA,
                FormFieldType.URL,
            ):
                label = field.label or field.field_id
                values[field.field_id] = TextValue(value=f"Sample {label}".strip())
        return SubmissionPayload(run_id="corpus", field_values=values)  # type: ignore[arg-type]

    @staticmethod
    def _load_form_schema(run_dir: str) -> WebsiteFormSchema:
        path = os.path.join(run_dir, "website_form_schema.json")
        with open(path, "r", encoding="utf-8") as f:
            return WebsiteFormSchema.model_validate(json.load(f))

    @staticmethod
    def _interactive_count(run_dir: str) -> int:
        path = os.path.join(run_dir, "interactivity_report.json")
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8") as f:
            return len(json.load(f).get("restored", []))

    # ── aggregation (pure) ───────────────────────────────────────────────────
    @classmethod
    def aggregate(cls, results: List[SiteResult]) -> CorpusReport:
        ok = [r for r in results if r.ok]
        metrics: Dict[str, MetricStats] = {}
        for name in _METRICS:
            values = [getattr(r, name) for r in ok if getattr(r, name) is not None]
            stats = cls._stats(values)
            if stats is not None:
                metrics[name] = stats
        return CorpusReport(
            total=len(results),
            succeeded=len(ok),
            failed=len(results) - len(ok),
            metrics=metrics,
            repurpose_success_buckets=cls._buckets(
                [r.repurpose_success for r in ok if r.repurpose_success is not None]
            ),
            sites=results,
        )

    @staticmethod
    def _stats(values: List[float]) -> Optional[MetricStats]:
        vals = sorted(values)
        n = len(vals)
        if n == 0:
            return None

        def pct(p: float) -> float:
            return vals[min(n - 1, int(p * n))]

        return MetricStats(
            n=n,
            mean=round(statistics.fmean(vals), 2),
            median=round(statistics.median(vals), 2),
            min=round(vals[0], 2),
            max=round(vals[-1], 2),
            p25=round(pct(0.25), 2),
            p75=round(pct(0.75), 2),
        )

    @staticmethod
    def _buckets(values: List[float]) -> Dict[str, int]:
        buckets = {"0": 0, "1-50": 0, "51-80": 0, "81-95": 0, "96-100": 0}
        for v in values:
            if v <= 0:
                buckets["0"] += 1
            elif v <= 50:
                buckets["1-50"] += 1
            elif v <= 80:
                buckets["51-80"] += 1
            elif v <= 95:
                buckets["81-95"] += 1
            else:
                buckets["96-100"] += 1
        return buckets


def default_corpus() -> List[str]:
    """The bundled fixture archetypes, if present."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    corpus_dir = os.path.join(here, "tests", "fixtures", "corpus")
    if not os.path.isdir(corpus_dir):
        return []
    return [
        os.path.join(corpus_dir, f)
        for f in sorted(os.listdir(corpus_dir))
        if f.endswith(".html")
    ]


def render_markdown(report: CorpusReport) -> str:
    """Human-readable distribution summary."""
    lines = [
        "# WIRE corpus evaluation",
        "",
        f"- Targets: **{report.total}**  |  succeeded: **{report.succeeded}**  "
        f"|  failed: **{report.failed}**",
        "",
        "## Metric distribution (succeeded sites)",
        "",
        "| metric | n | mean | median | min | max | p25 | p75 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, s in report.metrics.items():
        lines.append(
            f"| {name} | {s.n} | {s.mean} | {s.median} | {s.min} | {s.max} "
            f"| {s.p25} | {s.p75} |"
        )
    lines += ["", "## Repurpose-success buckets", ""]
    for bucket, count in report.repurpose_success_buckets.items():
        lines.append(f"- `{bucket}`: {count}")
    return "\n".join(lines) + "\n"


def write_report(report: CorpusReport, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "corpus_report.json"), "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))
    with open(os.path.join(out_dir, "corpus_report.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(report))


async def main(argv: List[str]) -> None:
    targets = argv or default_corpus()
    if not targets:
        print("No targets and no bundled corpus found.", file=sys.stderr)
        return
    runner = CorpusRunner()
    report = await runner.run(targets)
    write_report(report, runner.base_dir)
    print(render_markdown(report))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    asyncio.run(main(sys.argv[1:]))
