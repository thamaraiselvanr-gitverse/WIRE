"""Branch coverage for SubmissionValidator: optional/required top-level fields,
absent vs wrong-typed repeatable groups, and per-instance validation."""

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


def _blueprint():
    return InputBlueprint(
        slots={
            "slot_t": DataSlot(
                id="slot_t",
                type="text",
                constraint=SlotConstraint(allowed_types=["text"]),
                required=False,
            )
        }
    )


def _field(field_id, required=False):
    return FormField(
        field_id=field_id,
        slot_id="slot_t",
        cids_node_path="root",
        label=field_id,
        field_type=FormFieldType.TEXT,
        section_role=SectionRole.NAVIGATION,
        required=required,
    )


def test_optional_absent_and_required_missing():
    schema = WebsiteFormSchema(
        source_url="http://x",
        fields=[_field("opt", required=False), _field("req", required=True)],
    )
    # Neither supplied: optional -> success note, required -> hard failure.
    report = SubmissionValidator.validate(
        SubmissionPayload(run_id="r", field_values={}), schema, _blueprint()
    )
    assert not report.is_valid
    assert any("Required field 'req'" in f.message for f in report.hard_failures)
    assert any("Optional field 'opt'" in s.message for s in report.successes)


def test_valid_text_field_passes():
    schema = WebsiteFormSchema(source_url="http://x", fields=[_field("opt")])
    report = SubmissionValidator.validate(
        SubmissionPayload(run_id="r", field_values={"opt": TextValue(value="hello")}),
        schema,
        _blueprint(),
    )
    assert report.is_valid


def test_repeatable_group_absent_and_wrong_type():
    group = RepeatableFieldGroup(
        group_id="items",
        section_role=SectionRole.PORTFOLIO,
        label="Items",
        instance_count=1,
        template_fields=[_field("title", required=True)],
    )
    schema = WebsiteFormSchema(
        source_url="http://x", fields=[], repeatable_groups=[group]
    )

    # Absent group -> success note.
    absent = SubmissionValidator.validate(
        SubmissionPayload(run_id="r", field_values={}), schema, _blueprint()
    )
    assert absent.is_valid
    assert any("absent" in s.message for s in absent.successes)

    # Group field supplied as the wrong type -> hard failure.
    wrong = SubmissionValidator.validate(
        SubmissionPayload(run_id="r", field_values={"items": TextValue(value="x")}),
        schema,
        _blueprint(),
    )
    assert not wrong.is_valid
    assert any("expected repeatable group" in f.message for f in wrong.hard_failures)


def test_repeatable_group_instance_missing_required():
    group = RepeatableFieldGroup(
        group_id="items",
        section_role=SectionRole.PORTFOLIO,
        label="Items",
        instance_count=1,
        template_fields=[_field("title", required=True)],
    )
    schema = WebsiteFormSchema(
        source_url="http://x", fields=[], repeatable_groups=[group]
    )
    # One instance missing its required field.
    payload = SubmissionPayload(
        run_id="r",
        field_values={"items": RepeatableGroupValue(instances=[{}])},
    )
    report = SubmissionValidator.validate(payload, schema, _blueprint())
    assert not report.is_valid
    assert any("missing" in f.message.lower() for f in report.hard_failures)
