"""Drive ExecutionRouter.generate_transformation_prompt through the multi-modal
ingestion path (image upload) on a prepared run — covering the ingestion,
substitution, and prompt-generation branches. Offline (no LLM key)."""

import base64
import io
import os
import shutil

import pytest
from PIL import Image

from wire.orchestrator.execution_router import ExecutionRouter
from wire.schema.canonical import CanonicalDesignSchema, ComponentNode, DesignTokens
from wire.schema.input_blueprint import DataSlot, InputBlueprint, SlotConstraint
from wire.schema.semantic_schema import (
    FormField,
    FormFieldType,
    SectionRole,
    WebsiteFormSchema,
)
from wire.schema.submission_schema import ImageValue, SubmissionPayload


def _png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (24, 16), (10, 120, 200)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _prepare_run(run_dir: str):
    os.makedirs(os.path.join(run_dir, "assets"), exist_ok=True)
    root = ComponentNode(
        tag="div", children=[ComponentNode(tag="img", slot_id="slot_hero")]
    )
    cids = CanonicalDesignSchema(
        url="http://test.com", tokens=DesignTokens(), root=root
    )
    with open(os.path.join(run_dir, "schema_cids.json"), "w") as f:
        f.write(cids.model_dump_json())

    blueprint = InputBlueprint(
        slots={
            "slot_hero": DataSlot(
                id="slot_hero",
                type="image",
                constraint=SlotConstraint(allowed_types=["image"]),
                required=False,
            )
        }
    )
    with open(os.path.join(run_dir, "schema_blueprint.json"), "w") as f:
        f.write(blueprint.model_dump_json())

    form_schema = WebsiteFormSchema(
        source_url="http://test.com",
        fields=[
            FormField(
                field_id="hero_image",
                slot_id="slot_hero",
                cids_node_path="root > img:nth-child(1)",
                label="Hero Image",
                field_type=FormFieldType.IMAGE,
                section_role=SectionRole.HERO,
            )
        ],
    )
    with open(os.path.join(run_dir, "website_form_schema.json"), "w") as f:
        f.write(form_schema.model_dump_json())


@pytest.fixture
def run_dir():
    d = "output/test_run_subcov"
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_substitute_with_image_upload_ingests_and_builds_prompt(run_dir):
    _prepare_run(run_dir)
    router = ExecutionRouter()
    router.storage.base_dir = os.path.dirname(run_dir)

    payload = SubmissionPayload(
        run_id="test_run_subcov",
        field_values={
            "hero_image": ImageValue(
                value=_png_b64(),
                original_filename="brand-hero.png",
                content_type="image/png",
            )
        },
    )
    result = router.generate_transformation_prompt("test_run_subcov", payload)
    assert result.success is True
    # The uploaded image was ingested and stored under the run's assets.
    stored = os.listdir(os.path.join(run_dir, "assets", "user_uploads"))
    assert stored, "expected an ingested image on disk"
    assert os.path.exists(os.path.join(run_dir, "transformation_prompt.json"))


def test_substitute_ingestion_failure_fails_closed(run_dir):
    _prepare_run(run_dir)
    router = ExecutionRouter()
    router.storage.base_dir = os.path.dirname(run_dir)

    # Valid base64 that decodes to non-image bytes -> passes payload validation
    # but fails magic-byte verification during ingestion.
    bad = base64.b64encode(b"this is definitely not an image").decode()
    payload = SubmissionPayload(
        run_id="test_run_subcov",
        field_values={
            "hero_image": ImageValue(
                value=bad, original_filename="fake.png", content_type="image/png"
            )
        },
    )
    result = router.generate_transformation_prompt("test_run_subcov", payload)
    assert result.success is False
    assert any(
        "ingestion" in f.field_id or "ingestion" in f.message.lower()
        for f in result.validation_report.hard_failures
    )
