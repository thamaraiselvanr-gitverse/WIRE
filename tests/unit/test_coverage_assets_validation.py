import os

import httpx
import pytest

from wire.agents.extraction.asset_downloader import AssetDownloader
from wire.compilers.sanitizer import HtmlSanitizer
from wire.generation.submission_validator import SubmissionValidator
from wire.schema.input_blueprint import DataSlot, InputBlueprint, SlotConstraint
from wire.schema.semantic_schema import (
    FormField,
    FormFieldType,
    RepeatableFieldGroup,
    SectionRole,
    WebsiteFormSchema,
)
from wire.schema.submission_schema import (
    RepeatableGroupValue,
    SubmissionPayload,
    TextValue,
)


async def _asset_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.endswith(".css"):
        return httpx.Response(
            200,
            text="body { background: url(bg.png); }",
            headers={"content-type": "text/css"},
        )
    if url.endswith(".js"):
        return httpx.Response(
            200,
            text="console.log(1)",
            headers={"content-type": "application/javascript"},
        )
    if url.endswith(".png"):
        # Distinct bytes per URL so content-hash dedup treats bg.png and
        # pic.png as the different assets they are.
        return httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\n" + url.encode(),
            headers={"content-type": "image/png"},
        )
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_asset_downloader_localizes_css_js_img(tmp_path):
    html = (
        "<html><head>"
        '<link rel="stylesheet" href="style.css" integrity="x" crossorigin>'
        '<script src="app.js"></script>'
        '</head><body><img src="pic.png"></body></html>'
    )
    assets_dir = str(tmp_path / "assets")
    os.makedirs(assets_dir)

    dl = AssetDownloader()
    dl.client = httpx.AsyncClient(transport=httpx.MockTransport(_asset_handler))
    try:
        rewritten, assets = await dl.download_assets(
            "http://site.com/", html, assets_dir
        )
    finally:
        await dl.client.aclose()

    # Sources rewritten to local asset paths; integrity/crossorigin stripped.
    assert "assets/" in rewritten
    assert "integrity" not in rewritten
    # CSS, JS, IMG, plus the nested bg.png referenced inside the CSS.
    assert len(assets) >= 4
    # Files actually written to disk.
    assert len(os.listdir(assets_dir)) >= 4


def test_submission_validator_repeatable_group():
    tmpl = FormField(
        field_id="title",
        slot_id="slot_title",
        cids_node_path="root > div",
        label="Title",
        field_type=FormFieldType.TEXT,
        section_role=SectionRole.PORTFOLIO,
        required=True,
    )
    group = RepeatableFieldGroup(
        group_id="projects",
        section_role=SectionRole.PORTFOLIO,
        label="Projects",
        instance_count=1,
        template_fields=[tmpl],
    )
    schema = WebsiteFormSchema(
        source_url="http://x", fields=[], repeatable_groups=[group]
    )
    blueprint = InputBlueprint(
        slots={
            "slot_title": DataSlot(
                id="slot_title",
                type="text",
                constraint=SlotConstraint(allowed_types=["text"]),
            )
        }
    )

    # Valid: one instance with the required field present.
    ok = SubmissionPayload(
        run_id="r",
        field_values={
            "projects": RepeatableGroupValue(
                instances=[{"title": TextValue(value="My project")}]
            )
        },
    )
    assert SubmissionValidator.validate(ok, schema, blueprint).is_valid

    # Invalid: an instance missing the required field, plus an unknown field.
    bad = SubmissionPayload(
        run_id="r",
        field_values={
            "projects": RepeatableGroupValue(
                instances=[{"ghost": TextValue(value="x")}]
            )
        },
    )
    report = SubmissionValidator.validate(bad, schema, blueprint)
    assert not report.is_valid
    assert any("does not exist" in f.message for f in report.hard_failures)
    assert any("missing" in f.message for f in report.hard_failures)


def test_sanitizer_edge_cases():
    # Unsafe tags/handlers stripped; safe content kept.
    out = HtmlSanitizer.sanitize_html(
        '<div><script>x</script><a href="javascript:evil()">a</a>'
        '<a href="https://ok.com" id="good">ok</a>'
        '<img src="data:image/png;base64,AAAA"></div>'
    )
    assert "<script>" not in out
    assert "javascript:" not in out
    assert "good" in out
    assert HtmlSanitizer.sanitize_html("") == ""

    # Style sanitization keeps safe declarations, drops dangerous ones.
    safe = HtmlSanitizer._sanitize_style_string(
        "color: red; background: url(javascript:alert(1)); width: 100px"
    )
    assert "color: red" in safe
    assert "javascript" not in safe
    assert "width: 100px" in safe
