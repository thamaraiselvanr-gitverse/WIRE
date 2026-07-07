"""Phase-2 content-fit / layout-safety: adversarial content is flagged."""

from wire.evaluation.layout_safety import ContentFitValidator
from wire.evaluation.repurpose_harness import RepurposeEvaluator
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode, DesignTokens
from wire.schema.semantic_schema import (
    FormField,
    FormFieldType,
    SectionRole,
    WebsiteFormSchema,
)
from wire.schema.submission_schema import (
    ContentSubstitution,
    ImageValue,
    SubmissionPayload,
    SubstitutedValueRef,
    TextValue,
)


def _text_sub(field_id, value, original="Short", max_length=None, required=False):
    return ContentSubstitution(
        field_id=field_id,
        slot_id=f"slot_{field_id}",
        cids_node_path="root > p:nth-child(1)",
        section_role=SectionRole.HERO,
        original_value=original,
        substituted_value=SubstitutedValueRef(type="text", value=value),
        substitution_type="text_replace",
    )


class _Field:
    def __init__(self, required=False, max_length=None):
        self.required = required
        self.validation_rules = {"max_length": max_length}


def test_overflow_text_flagged():
    sub = _text_sub("headline", "x" * 200, original="Acme")
    report = ContentFitValidator().check(ComponentNode(tag="body"), [sub], {})
    kinds = {r.kind for r in report.risks}
    assert "text_overflow" in kinds
    assert report.safety_score < 100.0
    assert not report.passed


def test_exceeds_constraint_flagged():
    sub = _text_sub("headline", "y" * 60, original="y" * 55)  # not 2.5x overflow
    fields = {"slot_headline": _Field(max_length=40)}
    report = ContentFitValidator().check(ComponentNode(tag="body"), [sub], fields)
    assert any(r.kind == "text_exceeds_constraint" for r in report.risks)


def test_required_empty_flagged_high():
    sub = _text_sub("headline", "   ")
    fields = {"slot_headline": _Field(required=True)}
    report = ContentFitValidator().check(ComponentNode(tag="body"), [sub], fields)
    assert len(report.risks) == 1
    assert report.risks[0].kind == "required_empty"
    assert report.risks[0].severity == "high"
    assert report.safety_score == 60.0  # 100 - 40 high penalty


def test_aspect_ratio_shift_flagged():
    root = ComponentNode(
        tag="body",
        children=[
            ComponentNode(
                tag="img", attributes={"src": "a.png", "width": "800", "height": "200"}
            )
        ],
    )
    sub = ContentSubstitution(
        field_id="hero_img",
        slot_id="slot_img",
        cids_node_path="root > img:nth-child(1)",
        section_role=SectionRole.HERO,
        substituted_value=SubstitutedValueRef(
            type="image", value="tall.png", width=200, height=800  # inverted ratio
        ),
        substitution_type="image_replace",
    )
    report = ContentFitValidator().check(root, [sub], {})
    assert any(r.kind == "aspect_shift" for r in report.risks)


def test_good_fit_is_safe():
    sub = _text_sub("headline", "A New Headline", original="Old Headline Here")
    report = ContentFitValidator().check(ComponentNode(tag="body"), [sub], {})
    assert report.passed
    assert report.safety_score == 100.0


def test_layout_safety_folds_into_repurpose_score():
    # An overflowing headline should pull the composite below a clean run.
    cids = CanonicalDesignSchema(
        url="https://ex.test",
        tokens=DesignTokens(),
        root=ComponentNode(
            tag="body",
            children=[
                ComponentNode(
                    tag="h1",
                    attributes={"id": "t"},
                    children=[ComponentNode(tag="#text", text_content="Acme")],
                )
            ],
        ),
    )
    schema = WebsiteFormSchema(
        source_url="https://ex.test",
        fields=[
            FormField(
                field_id="headline",
                slot_id="slot_h1_1",
                cids_node_path="root > h1:nth-child(1)",
                label="Hero Heading",
                field_type=FormFieldType.TEXT,
                section_role=SectionRole.HERO,
                original_value="Acme",
            )
        ],
    )
    # Bind the slot_id onto the node so substitution targets it.
    cids.root.children[0].slot_id = "slot_h1_1"

    good = SubmissionPayload(
        run_id="r", field_values={"headline": TextValue(value="Acme Two")}
    )
    bad = SubmissionPayload(
        run_id="r", field_values={"headline": TextValue(value="Z" * 100)}
    )
    good_report, _ = RepurposeEvaluator().evaluate(
        cids, schema, good, original_html="<body><h1>Acme</h1></body>"
    )
    bad_report, _ = RepurposeEvaluator().evaluate(
        cids, schema, bad, original_html="<body><h1>Acme</h1></body>"
    )
    assert good_report.layout_safety_score == 100.0
    assert bad_report.layout_safety_score < 100.0
    assert bad_report.success_percent < good_report.success_percent


def test_image_value_dims_flow_into_substitution():
    # SubstitutionMapper should carry width/height from the submitted image.
    from wire.generation.substitution_mapper import SubstitutionMapper

    cids = CanonicalDesignSchema(
        url="https://ex.test",
        tokens=DesignTokens(),
        root=ComponentNode(
            tag="body", children=[ComponentNode(tag="img", attributes={"src": "o.png"})]
        ),
    )
    schema = WebsiteFormSchema(
        source_url="https://ex.test",
        fields=[
            FormField(
                field_id="img",
                slot_id="slot_img_1",
                cids_node_path="root > img:nth-child(1)",
                label="Image",
                field_type=FormFieldType.IMAGE,
                section_role=SectionRole.HERO,
            )
        ],
    )
    iv = ImageValue(
        value="data", original_filename="pic.png", content_type="image/png"
    )
    iv.width = 640
    iv.height = 480
    payload = SubmissionPayload(run_id="r", field_values={"img": iv})
    subs = SubstitutionMapper.map(cids.root, payload, schema)
    assert subs[0].substituted_value.width == 640
    assert subs[0].substituted_value.height == 480
