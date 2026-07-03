from typing import Any, List

from wire.schema.canonical import ComponentNode
from wire.schema.submission_schema import (
    ContentSubstitution,
    SubmissionPayload,
    SubstitutedValueRef,
)


class SubstitutionMapper:
    """
    Maps validated SubmissionPayload values to ContentSubstitution records
    representing edits in CIDS slots.
    """

    @staticmethod
    def map(
        cids_root: ComponentNode, payload: SubmissionPayload, form_schema: Any
    ) -> List[ContentSubstitution]:
        substitutions: List[ContentSubstitution] = []

        schema_fields = {f.field_id: f for f in form_schema.fields}
        schema_groups = {
            g.group_id: g for g in getattr(form_schema, "repeatable_groups", [])
        }

        # 1. Map top-level fields
        for field_id, submitted_val in payload.field_values.items():
            if field_id in schema_fields:
                form_field = schema_fields[field_id]

                sub_type, ref_type = SubstitutionMapper._resolve_types(
                    form_field.field_type.value
                )

                substitutions.append(
                    ContentSubstitution(
                        field_id=field_id,
                        slot_id=form_field.slot_id,
                        cids_node_path=form_field.cids_node_path,
                        section_role=form_field.section_role,
                        original_value=form_field.original_value,
                        substituted_value=SubstitutedValueRef(
                            type=ref_type,
                            value=submitted_val.value,
                            extracted_text=getattr(
                                submitted_val, "extracted_text", None
                            ),
                        ),
                        substitution_type=sub_type,
                    )
                )

        # 2. Map repeatable group fields
        for group_id, submitted_val in payload.field_values.items():
            if group_id in schema_groups:
                group = schema_groups[group_id]
                original_count = group.instance_count
                template_fields = {f.field_id: f for f in group.template_fields}

                for inst_idx, instance in enumerate(submitted_val.instances):
                    is_new_instance = inst_idx >= original_count

                    for f_id, val in instance.items():
                        if f_id in template_fields:
                            template_field = template_fields[f_id]

                            base_sub_type, ref_type = SubstitutionMapper._resolve_types(
                                template_field.field_type.value
                            )
                            sub_type = (
                                "repeatable_instance_add"
                                if is_new_instance
                                else base_sub_type
                            )

                            # Estimate the path for existing repeat items by modifying the index
                            adjusted_path = SubstitutionMapper._adjust_path_index(
                                template_field.cids_node_path, inst_idx
                            )

                            substitutions.append(
                                ContentSubstitution(
                                    field_id=f"{group_id}[{inst_idx}].{f_id}",
                                    slot_id=template_field.slot_id,
                                    cids_node_path=adjusted_path,
                                    section_role=template_field.section_role,
                                    original_value=(
                                        template_field.original_value
                                        if not is_new_instance
                                        else None
                                    ),
                                    substituted_value=SubstitutedValueRef(
                                        type=ref_type,
                                        value=val.value,
                                        extracted_text=getattr(
                                            val, "extracted_text", None
                                        ),
                                    ),
                                    substitution_type=sub_type,
                                )
                            )

        return substitutions

    @staticmethod
    def _resolve_types(field_type: str) -> tuple:
        """Map a form field type to (substitution_type, substituted_ref_type)."""
        mapping = {
            "image": ("image_replace", "image"),
            "video": ("media_replace", "video"),
            "audio": ("media_replace", "audio"),
            "document": ("document_replace", "document"),
            "url": ("text_replace", "url"),
        }
        return mapping.get(field_type, ("text_replace", "text"))

    @staticmethod
    def _adjust_path_index(node_path: str, instance_idx: int) -> str:
        """
        Adjusts the sibling child index in the CIDS path to reference the correct instance.
        For example: root > div:nth-child(2) > div:nth-child(1) -> root > div:nth-child(2) > div:nth-child(1 + instance_idx)
        """
        # If the path contains nth-child, we update the last one or the one corresponding to the repeats.
        # A simple robust heuristic: find the last occurrence of :nth-child(N) and replace N with (N + instance_idx)
        # since the repeatable items are siblings of that node.
        if ":nth-child(" not in node_path:
            return node_path

        parts = node_path.split(" > ")
        # Find the node that corresponds to the repeat item (usually the sibling of the template field's parent)
        # In a typical repeat list, the repeat container is parent of the items.
        # e.g., root > div:nth-child(3) > div:nth-child(1) > span
        # The repeat items are the children of root > div:nth-child(3), which is div:nth-child(1).
        # So we adjust the second-to-last or last nth-child node.
        # Let's find the first node starting from the end of parts that has nth-child and contains a child class.
        # For generality, we can search for the last part that has ':nth-child(' but isn't the leaf tag unless leaf is the block itself.
        for i in range(len(parts) - 1, -1, -1):
            if ":nth-child(" in parts[i]:
                try:
                    prefix, rest = parts[i].split(":nth-child(", 1)
                    num_str, suffix = rest.split(")", 1)
                    base_idx = int(num_str)
                    new_idx = base_idx + instance_idx
                    parts[i] = f"{prefix}:nth-child({new_idx}){suffix}"
                    break
                except ValueError:
                    pass

        return " > ".join(parts)
