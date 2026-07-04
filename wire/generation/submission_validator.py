from typing import Any, List

from wire.schema.input_blueprint import InputBlueprint
from wire.schema.semantic_schema import FormField
from wire.schema.submission_schema import (
    RepeatableGroupValue,
    SubmissionPayload,
    SubmittedValue,
    ValidationItem,
    ValidationSummary,
)


class SubmissionValidator:
    """
    Validates SubmissionPayload against WebsiteFormSchema (or PortfolioFormSchema)
    and InputBlueprint constraints.
    """

    @staticmethod
    def validate(
        payload: SubmissionPayload,
        form_schema: Any,  # WebsiteFormSchema or PortfolioFormSchema
        blueprint: InputBlueprint,
    ) -> ValidationSummary:
        hard_failures: List[ValidationItem] = []
        soft_warnings: List[ValidationItem] = []
        successes: List[ValidationItem] = []

        # Build maps for lookup
        schema_fields = {f.field_id: f for f in form_schema.fields}
        schema_groups = {
            g.group_id: g for g in getattr(form_schema, "repeatable_groups", [])
        }

        # Check for unexpected fields in the top-level payload (prevent fabrication)
        for field_id in payload.field_values:
            if field_id not in schema_fields and field_id not in schema_groups:
                hard_failures.append(
                    ValidationItem(
                        field_id=field_id,
                        message=f"Field '{field_id}' does not exist in the form schema.",
                    )
                )

        # 1. Validate top-level fields
        for field_id, form_field in schema_fields.items():
            submitted_val = payload.field_values.get(field_id)

            if submitted_val is None:
                # Field is missing
                if form_field.required:
                    hard_failures.append(
                        ValidationItem(
                            field_id=field_id,
                            message=f"Required field '{field_id}' is missing.",
                        )
                    )
                else:
                    successes.append(
                        ValidationItem(
                            field_id=field_id,
                            message=f"Optional field '{field_id}' is absent.",
                        )
                    )
                continue

            # Validate type alignment and values
            err_msg = SubmissionValidator._check_type_alignment(
                form_field, submitted_val
            )
            if err_msg:
                hard_failures.append(ValidationItem(field_id=field_id, message=err_msg))
                continue

            # Delegate to InputBlueprint
            val_to_check = getattr(submitted_val, "value", "")
            res = blueprint.validate_input(
                form_field.slot_id, val_to_check, strict=True
            )
            if not res["valid"]:
                hard_failures.append(
                    ValidationItem(field_id=field_id, message=res["message"])
                )
            elif res.get("severity") == "soft":
                soft_warnings.append(
                    ValidationItem(field_id=field_id, message=res["message"])
                )
            else:
                successes.append(
                    ValidationItem(field_id=field_id, message=res["message"])
                )

        # 2. Validate repeatable groups
        for group_id, group in schema_groups.items():
            submitted_val = payload.field_values.get(group_id)

            if submitted_val is None:
                successes.append(
                    ValidationItem(
                        field_id=group_id,
                        message=f"Repeatable group '{group_id}' is absent.",
                    )
                )
                continue

            if not isinstance(submitted_val, RepeatableGroupValue):
                hard_failures.append(
                    ValidationItem(
                        field_id=group_id,
                        message=f"Field '{group_id}' expected repeatable group, got {type(submitted_val).__name__}.",
                    )
                )
                continue

            # Validate each instance in the repeatable group
            template_fields = {f.field_id: f for f in group.template_fields}
            for inst_idx, instance in enumerate(submitted_val.instances):
                # Check for unexpected fields in the instance
                for f_id in instance:
                    if f_id not in template_fields:
                        hard_failures.append(
                            ValidationItem(
                                field_id=f"{group_id}[{inst_idx}].{f_id}",
                                message=f"Field '{f_id}' does not exist in repeatable group template.",
                            )
                        )

                for f_id, form_field in template_fields.items():
                    val = instance.get(f_id)
                    inst_field_id = f"{group_id}[{inst_idx}].{f_id}"

                    if val is None:
                        if form_field.required:
                            hard_failures.append(
                                ValidationItem(
                                    field_id=inst_field_id,
                                    message=f"Required repeatable field '{f_id}' is missing in instance {inst_idx}.",
                                )
                            )
                        continue

                    # Validate type alignment
                    err_msg = SubmissionValidator._check_type_alignment(form_field, val)
                    if err_msg:
                        hard_failures.append(
                            ValidationItem(field_id=inst_field_id, message=err_msg)
                        )
                        continue

                    # Delegate validation
                    res = blueprint.validate_input(
                        form_field.slot_id, getattr(val, "value", ""), strict=True
                    )
                    if not res["valid"]:
                        hard_failures.append(
                            ValidationItem(
                                field_id=inst_field_id, message=res["message"]
                            )
                        )
                    elif res.get("severity") == "soft":
                        soft_warnings.append(
                            ValidationItem(
                                field_id=inst_field_id, message=res["message"]
                            )
                        )
                    else:
                        successes.append(
                            ValidationItem(
                                field_id=inst_field_id, message=res["message"]
                            )
                        )

        is_valid = len(hard_failures) == 0
        return ValidationSummary(
            is_valid=is_valid,
            hard_failures=hard_failures,
            soft_warnings=soft_warnings,
            successes=successes,
        )

    # Form field type -> the submission value type(s) it accepts.
    _TYPE_COMPAT = {
        "text": {"text"},
        "textarea": {"text"},
        # A document (with extracted text) is an acceptable source for text.
        "image": {"image"},
        "video": {"video"},
        "audio": {"audio"},
        "document": {"document"},
        "url": {"url"},
        "color": {"text"},
    }

    # Content-type prefix each media field family requires (media compatibility).
    _MEDIA_CT_PREFIX = {
        "image": "image/",
        "video": "video/",
        "audio": "audio/",
    }

    @staticmethod
    def _check_type_alignment(
        form_field: FormField, submitted_val: SubmittedValue
    ) -> str | None:
        expected_type = form_field.field_type.value
        actual_type = submitted_val.type

        accepted = SubmissionValidator._TYPE_COMPAT.get(expected_type)
        # 'text' fields may also accept a document (its extracted text is used).
        if expected_type in ("text", "textarea") and actual_type == "document":
            return None
        if accepted is not None and actual_type not in accepted:
            return (
                f"Type mismatch: field '{form_field.field_id}' expected "
                f"{expected_type}, got {actual_type}."
            )

        # Media compatibility: the uploaded file's declared content type must
        # match the media family (an .mp3 cannot fill a video slot, etc.).
        prefix = SubmissionValidator._MEDIA_CT_PREFIX.get(expected_type)
        if prefix is not None:
            content_type = getattr(submitted_val, "content_type", "") or ""
            if content_type and not content_type.lower().startswith(prefix):
                return (
                    f"Media incompatibility: field '{form_field.field_id}' expects "
                    f"{expected_type} ({prefix}*), got content type '{content_type}'."
                )

        return None
