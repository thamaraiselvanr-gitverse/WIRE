"""Phase-0 repurposing-success harness: apply substitutions + honest scoring."""

from wire.evaluation.repurpose_harness import (
    RepurposeEvaluator,
    apply_substitutions,
)
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode, DesignTokens
from wire.schema.semantic_schema import (
    FormField,
    FormFieldType,
    SectionRole,
    WebsiteFormSchema,
)
from wire.schema.submission_schema import SubmissionPayload, TextValue


def _cids():
    # root(body) > h1#title("Old Title") ; > img (src=old.png)
    return CanonicalDesignSchema(
        url="https://ex.test",
        tokens=DesignTokens(),
        root=ComponentNode(
            tag="body",
            children=[
                ComponentNode(
                    tag="h1",
                    attributes={"id": "title"},
                    children=[ComponentNode(tag="#text", text_content="Old Title")],
                ),
                ComponentNode(tag="img", attributes={"src": "old.png"}),
            ],
        ),
    )


def _schema():
    return WebsiteFormSchema(
        source_url="https://ex.test",
        fields=[
            FormField(
                field_id="headline",
                slot_id="slot_headline",
                cids_node_path="root > h1:nth-child(1)",
                label="Headline",
                field_type=FormFieldType.TEXT,
                section_role=SectionRole.HERO,
                original_value="Old Title",
            ),
            FormField(
                field_id="hero_img",
                slot_id="slot_img",
                cids_node_path="root > img:nth-child(2)",
                label="Hero image",
                field_type=FormFieldType.IMAGE,
                section_role=SectionRole.HERO,
            ),
        ],
    )


def test_apply_substitutions_sets_text_and_src_by_path():
    from wire.generation.substitution_mapper import SubstitutionMapper

    cids = _cids()
    payload = SubmissionPayload(
        run_id="r",
        field_values={
            "headline": TextValue(value="Brand New Headline"),
            "hero_img": TextValue(value="mine.png"),  # image field, path value
        },
    )
    subs = SubstitutionMapper.map(cids.root, payload, _schema())
    mutated, outcomes = apply_substitutions(cids.root, subs)

    h1 = next(c for c in mutated.children if c.tag == "h1")
    img = next(c for c in mutated.children if c.tag == "img")
    assert h1.children[0].text_content == "Brand New Headline"
    assert img.attributes["src"] == "mine.png"
    assert all(o.applied for o in outcomes)
    # Original tree is untouched (deep-copied).
    orig_h1 = next(c for c in cids.root.children if c.tag == "h1")
    assert orig_h1.children[0].text_content == "Old Title"


def test_evaluate_full_success_when_everything_lands():
    cids = _cids()
    original_html = "<body><h1>Old Title</h1><img src='old.png'/></body>"
    payload = SubmissionPayload(
        run_id="r",
        field_values={
            "headline": TextValue(value="Brand New Headline"),
            "hero_img": TextValue(value="mine.png"),
        },
    )
    report, html = RepurposeEvaluator().evaluate(
        cids, _schema(), payload, original_html=original_html
    )
    assert report.slot_fill_rate == 1.0
    assert report.content_presence_rate == 1.0
    assert "Brand New Headline" in html
    assert report.structural_score is not None
    assert report.success_percent > 0


def test_unresolvable_path_lowers_slot_fill():
    cids = _cids()
    schema = WebsiteFormSchema(
        source_url="https://ex.test",
        fields=[
            FormField(
                field_id="headline",
                slot_id="s",
                cids_node_path="root > h9:nth-child(99)",  # no such node
                label="Headline",
                field_type=FormFieldType.TEXT,
                section_role=SectionRole.HERO,
            )
        ],
    )
    payload = SubmissionPayload(
        run_id="r", field_values={"headline": TextValue(value="Nope")}
    )
    report, _ = RepurposeEvaluator().evaluate(cids, schema, payload)
    assert report.slot_fill_rate == 0.0
    assert report.applied_fields == 0
    assert report.fields[0].reason == "path_not_found"
    # Nothing landed -> honest zero, not a vacuous green.
    assert report.success_percent == 0.0


def test_empty_payload_scores_zero_not_vacuous_full():
    # A page whose schema exposed slots but no content was submitted has NOT
    # been repurposed — success must be 0, not 100 from empty-denominator rates.
    cids = _cids()
    report, _ = RepurposeEvaluator().evaluate(
        cids,
        _schema(),
        SubmissionPayload(run_id="r", field_values={}),
        original_html="<body><h1>Old Title</h1><img src='old.png'/></body>",
    )
    assert report.applied_fields == 0
    assert report.success_percent == 0.0
    # The schema capability is still reported so the gap is visible.
    assert report.schema_field_count == 2


def test_apply_handles_nested_text_and_image_alt():
    from wire.schema.submission_schema import ContentSubstitution, SubstitutedValueRef

    # div > span > #text : the text target is a nested descendant, not direct.
    root = ComponentNode(
        tag="body",
        children=[
            ComponentNode(
                tag="div",
                children=[
                    ComponentNode(
                        tag="span",
                        children=[ComponentNode(tag="#text", text_content="deep")],
                    )
                ],
            ),
            ComponentNode(tag="img", attributes={"src": "old.png"}),
        ],
    )
    subs = [
        ContentSubstitution(
            field_id="t",
            slot_id="s1",
            cids_node_path="root > div:nth-child(1)",
            section_role=SectionRole.HERO,
            substituted_value=SubstitutedValueRef(type="text", value="fresh"),
            substitution_type="text_replace",
        ),
        ContentSubstitution(
            field_id="i",
            slot_id="s2",
            cids_node_path="root > img:nth-child(2)",
            section_role=SectionRole.HERO,
            substituted_value=SubstitutedValueRef(
                type="image", value="new.png", alt_text="A logo"
            ),
            substitution_type="image_replace",
        ),
    ]
    mutated, outcomes = apply_substitutions(root, subs)
    span_text = mutated.children[0].children[0].children[0]
    assert span_text.text_content == "fresh"
    assert mutated.children[1].attributes["src"] == "new.png"
    assert mutated.children[1].attributes["alt"] == "A logo"
    assert all(o.applied for o in outcomes)


def test_evaluate_repurpose_loads_run_and_writes_artifacts(tmp_path):
    import json

    from wire.orchestrator.execution_router import ExecutionRouter

    router = ExecutionRouter()
    router.storage.base_dir = str(tmp_path)
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    (run_dir / "schema_cids.json").write_text(
        _cids().model_dump_json(), encoding="utf-8"
    )
    (run_dir / "website_form_schema.json").write_text(
        _schema().model_dump_json(), encoding="utf-8"
    )
    (run_dir / "output_editable.html").write_text(
        "<body><h1>Old Title</h1><img src='old.png'/></body>", encoding="utf-8"
    )

    payload = SubmissionPayload(
        run_id="run1",
        field_values={"headline": TextValue(value="Repurposed Headline")},
    )
    report = router.evaluate_repurpose("run1", payload)

    assert report.applied_fields == 1
    assert report.success_percent > 0
    assert (run_dir / "substituted_editable.html").exists()
    saved = json.loads((run_dir / "repurpose_report.json").read_text())
    assert saved["success_percent"] == report.success_percent
    assert "Repurposed Headline" in (run_dir / "substituted_editable.html").read_text()


def test_evaluate_repurpose_missing_run_raises(tmp_path):
    from wire.orchestrator.execution_router import ExecutionRouter

    router = ExecutionRouter()
    router.storage.base_dir = str(tmp_path)
    payload = SubmissionPayload(run_id="ghost", field_values={})
    try:
        router.evaluate_repurpose("ghost", payload)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_visual_score_folds_into_composite():
    cids = _cids()
    payload = SubmissionPayload(
        run_id="r",
        field_values={"headline": TextValue(value="Hi")},
    )
    schema = WebsiteFormSchema(
        source_url="https://ex.test", fields=[_schema().fields[0]]
    )
    report, _ = RepurposeEvaluator().evaluate(
        cids,
        schema,
        payload,
        original_html="<body><h1>Old Title</h1></body>",
        visual_score=50.0,
    )
    assert report.visual_score == 50.0
    # Composite is the mean of the available signals, so the 50 pulls it down.
    assert report.success_percent < 100.0
