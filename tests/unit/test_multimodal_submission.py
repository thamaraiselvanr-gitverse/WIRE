import base64
import os
import tempfile

from wire.generation.submission_validator import SubmissionValidator
from wire.generation.substitution_mapper import SubstitutionMapper
from wire.orchestrator.execution_router import ExecutionRouter
from wire.schema.canonical import ComponentNode
from wire.schema.input_blueprint import DataSlot, InputBlueprint, SlotConstraint
from wire.schema.semantic_schema import (
    FormField,
    FormFieldType,
    SectionRole,
    WebsiteFormSchema,
)
from wire.schema.submission_schema import (
    AudioValue,
    DocumentValue,
    SubmissionPayload,
    VideoValue,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _field(fid, ftype):
    return FormField(
        field_id=fid,
        slot_id=f"slot_{fid}",
        cids_node_path="root > div",
        label=fid,
        field_type=ftype,
        section_role=SectionRole.HERO,
    )


def _schema():
    return WebsiteFormSchema(
        source_url="http://x",
        fields=[
            _field("promo", FormFieldType.VIDEO),
            _field("jingle", FormFieldType.AUDIO),
            _field("bio", FormFieldType.DOCUMENT),
        ],
    )


def _blueprint():
    return InputBlueprint(
        slots={
            "slot_promo": DataSlot(
                id="slot_promo",
                type="video",
                constraint=SlotConstraint(allowed_types=["video"]),
            ),
            "slot_jingle": DataSlot(
                id="slot_jingle",
                type="audio",
                constraint=SlotConstraint(allowed_types=["audio"]),
            ),
            "slot_bio": DataSlot(
                id="slot_bio",
                type="document",
                constraint=SlotConstraint(allowed_types=["document"]),
            ),
        }
    )


def test_validation_accepts_matching_media_types():
    payload = SubmissionPayload(
        run_id="r",
        field_values={
            "promo": VideoValue(
                value="x", original_filename="a.mp4", content_type="video/mp4"
            ),
            "jingle": AudioValue(
                value="y", original_filename="a.mp3", content_type="audio/mpeg"
            ),
            "bio": DocumentValue(
                value="z", original_filename="cv.pdf", content_type="application/pdf"
            ),
        },
    )
    report = SubmissionValidator.validate(payload, _schema(), _blueprint())
    assert report.is_valid, report.hard_failures


def test_validation_rejects_media_content_type_mismatch():
    # An audio content type in a video field must fail media compatibility.
    payload = SubmissionPayload(
        run_id="r",
        field_values={
            "promo": VideoValue(
                value="x", original_filename="a.mp3", content_type="audio/mpeg"
            ),
        },
    )
    report = SubmissionValidator.validate(payload, _schema(), _blueprint())
    assert not report.is_valid
    assert any("Media incompatibility" in f.message for f in report.hard_failures)


def test_substitution_mapper_emits_media_and_document_types():
    payload = SubmissionPayload(
        run_id="r",
        field_values={
            "promo": VideoValue(
                value="assets/user_uploads/v.mp4",
                original_filename="a.mp4",
                content_type="video/mp4",
            ),
            "bio": DocumentValue(
                value="assets/user_uploads/c.pdf",
                original_filename="cv.pdf",
                content_type="application/pdf",
                extracted_text="Extracted bio",
            ),
        },
    )
    subs = SubstitutionMapper.map(ComponentNode(tag="div"), payload, _schema())
    by_field = {s.field_id: s for s in subs}
    assert by_field["promo"].substitution_type == "media_replace"
    assert by_field["promo"].substituted_value.type == "video"
    assert by_field["bio"].substitution_type == "document_replace"
    assert by_field["bio"].substituted_value.extracted_text == "Extracted bio"


def test_ingest_dispatch_document_sets_path_and_text():
    with tempfile.TemporaryDirectory() as d:
        assets = os.path.join(d, "assets")
        os.makedirs(assets)
        doc = DocumentValue(
            value=_b64(b"Resume summary text"),
            original_filename="resume.txt",
            content_type="text/plain",
        )
        ExecutionRouter._ingest_submitted_value(doc, assets)
        assert doc.value.startswith("assets/user_uploads/")
        assert "Resume summary text" in (doc.extracted_text or "")
