"""
Form Schema Compiler — General-Purpose Form Schema from CIDS Tree.

Walks the classified CIDS tree, collects all nodes with slot_id bindings,
and compiles them into a WebsiteFormSchema. Never fabricates form fields
without a real, traceable slot_id.
"""

from typing import Dict, List, Optional

import structlog

from wire.schema.canonical import ComponentNode
from wire.schema.input_blueprint import DataSlot, InputBlueprint
from wire.schema.semantic_schema import (
    ClassifiedSection,
    ContentState,
    FormField,
    FormFieldType,
    RepeatableFieldGroup,
    SectionRole,
    WebsiteFormSchema,
)
from wire.semantic.placeholder_detector import PlaceholderDetector

logger = structlog.get_logger(__name__)


class FormSchemaCompiler:
    """
    Compiles a classified CIDS tree into a WebsiteFormSchema.

    Critical constraint: NEVER fabricate a FormField without a real slot_id.
    Sections with no slot_id children appear in read_only_sections list,
    not as editable fields.
    """

    def __init__(self, placeholder_detector: PlaceholderDetector) -> None:
        self.placeholder_detector = placeholder_detector

    def compile(
        self,
        cids_root: ComponentNode,
        classified_sections: List[ClassifiedSection],
        input_blueprint: InputBlueprint,
        source_url: str = "",
    ) -> WebsiteFormSchema:
        """
        Compile a classified CIDS tree into a WebsiteFormSchema.

        For each slot_id in the existing InputBlueprint: resolves parent
        classified section, determines FormFieldType, runs placeholder
        detection, and applies required from existing validation logic.
        """
        # Build section map: node_path -> ClassifiedSection
        section_map = {cs.node_path: cs for cs in classified_sections}

        # Walk tree collecting slot_id-bearing nodes
        fields = self._walk_tree(cids_root, "root", section_map, input_blueprint)

        # Determine which sections have fields and which are read-only
        sections_with_fields = {f.section_role for f in fields}
        all_sections = [cs.section_role for cs in classified_sections]
        read_only_sections = [
            cs.node_path
            for cs in classified_sections
            if cs.section_role not in sections_with_fields
            and cs.section_role != SectionRole.UNKNOWN
        ]

        # Detect repeatable groups
        repeatable_groups = self._detect_repeatable_groups(fields, classified_sections)

        # Collect needs_confirmation fields
        needs_confirmation = [
            f.field_id
            for f in fields
            if f.content_state == ContentState.NEEDS_USER_CONFIRMATION
        ]

        schema = WebsiteFormSchema(
            source_url=source_url,
            sections=list(dict.fromkeys(all_sections)),  # preserve order, dedupe
            fields=fields,
            repeatable_groups=repeatable_groups,
            needs_confirmation=needs_confirmation,
            read_only_sections=read_only_sections,
        )

        logger.info(
            "form_schema_compiled",
            total_fields=len(fields),
            total_sections=len(all_sections),
            read_only_sections=len(read_only_sections),
            repeatable_groups=len(repeatable_groups),
            needs_confirmation=len(needs_confirmation),
        )
        return schema

    def _walk_tree(
        self,
        node: ComponentNode,
        path: str,
        section_map: Dict[str, ClassifiedSection],
        input_blueprint: InputBlueprint,
    ) -> List[FormField]:
        """
        Recursively walk tree collecting slot_id-bearing nodes.
        """
        fields: List[FormField] = []

        if node.slot_id and node.slot_id in input_blueprint.slots:
            slot = input_blueprint.slots[node.slot_id]
            section = self._find_parent_section(path, section_map)
            section_role = section.section_role if section else SectionRole.UNKNOWN
            classification_confidence = section.confidence if section else 0.0

            # Resolve field type from slot's type
            field_type = self._resolve_field_type(slot)

            # Run placeholder detection on original value. Parsed element text
            # lives in a #text child, not node.text_content, so fall back to it
            # — otherwise headings/paragraphs surface as blank current content.
            original_value = (
                self._node_text(node)
                or node.attributes.get("src", "")
                or node.attributes.get("href", "")
            )
            placeholder_result = self.placeholder_detector.evaluate_field(
                original_value, field_type
            )

            # Determine required from existing validation logic
            required = slot.required

            field = FormField(
                field_id=f"{section_role.value}_{node.slot_id}",
                slot_id=node.slot_id,
                cids_node_path=path,
                label=self._generate_label(node.slot_id, section_role),
                field_type=field_type,
                section_role=section_role,
                required=required,
                content_state=placeholder_result.content_state,
                original_value=original_value if original_value else None,
                classification_confidence=classification_confidence,
                placeholder_confidence=placeholder_result.confidence,
                validation_rules={
                    "max_length": slot.constraint.max_length,
                    "max_width": slot.constraint.max_width,
                    "max_height": slot.constraint.max_height,
                    "allowed_types": slot.constraint.allowed_types,
                },
            )
            fields.append(field)

        # Recurse into children
        for idx, child in enumerate(node.children):
            child_path = f"{path} > {child.tag}:nth-child({idx + 1})"
            fields.extend(
                self._walk_tree(child, child_path, section_map, input_blueprint)
            )

        return fields

    @staticmethod
    def _node_text(node: ComponentNode) -> str:
        """The node's own text: its ``text_content`` or first ``#text`` child."""
        if node.text_content:
            return node.text_content
        for child in node.children:
            if child.tag == "#text" and child.text_content:
                return child.text_content
        return ""

    def _find_parent_section(
        self, node_path: str, section_map: Dict[str, ClassifiedSection]
    ) -> Optional[ClassifiedSection]:
        """
        Find the classified section that contains this node path.

        Walks up the path hierarchy to find the nearest section ancestor.
        """
        # Try direct match first
        if node_path in section_map:
            return section_map[node_path]

        # Walk up: strip the last segment from the path
        parts = node_path.split(" > ")
        for i in range(len(parts) - 1, 0, -1):
            ancestor_path = " > ".join(parts[:i])
            if ancestor_path in section_map:
                return section_map[ancestor_path]

        # Fallback: return the first section if only one exists
        if len(section_map) == 1:
            return next(iter(section_map.values()))

        return None

    def _resolve_field_type(self, slot: DataSlot) -> FormFieldType:
        """
        Map DataSlot.type to FormFieldType.

        - 'text' with max_length > 200 → TEXTAREA
        - 'text' otherwise → TEXT
        - 'image' → IMAGE
        - 'video'/'audio' → URL
        """
        if slot.type == "text":
            if slot.constraint.max_length and slot.constraint.max_length > 200:
                return FormFieldType.TEXTAREA
            return FormFieldType.TEXT
        elif slot.type == "image":
            return FormFieldType.IMAGE
        elif slot.type in ("video", "audio"):
            return FormFieldType.URL
        return FormFieldType.TEXT

    def _generate_label(self, slot_id: str, section_role: SectionRole) -> str:
        """
        Generate a human-readable label for a form field.

        Uses deterministic templates for unambiguous combinations,
        falls back to cleaned-up slot_id.
        """
        # Heuristic slot_ids embed the element kind (slot_{tag}_{n}); use it so
        # a hero's heading, body, and button don't all read "Hero Title".
        parts = slot_id.split("_")
        if len(parts) >= 3 and parts[0] == "slot":
            kind_map = {
                "h1": "Heading", "h2": "Heading", "h3": "Subheading",
                "h4": "Subheading", "h5": "Subheading", "h6": "Subheading",
                "p": "Text", "span": "Text", "a": "Link", "button": "Button",
                "li": "List Item", "img": "Image", "blockquote": "Quote",
                "figcaption": "Caption", "caption": "Caption", "label": "Label",
                "td": "Cell", "th": "Header Cell", "summary": "Summary",
                "cite": "Citation", "strong": "Text", "em": "Text",
            }  # fmt: skip
            kind = kind_map.get(parts[1])
            if kind:
                role_name = (
                    section_role.value.replace("_", " ").title()
                    if section_role != SectionRole.UNKNOWN
                    else ""
                )
                return f"{role_name} {kind}".strip()

        # Deterministic templates for known combinations
        templates = {
            (SectionRole.HERO, "text"): "Hero Title",
            (SectionRole.HERO, "image"): "Hero Image",
            (SectionRole.ABOUT, "text"): "About Description",
            (SectionRole.ABOUT, "image"): "About Image",
            (SectionRole.CONTACT, "url"): "Contact Link",
            (SectionRole.CONTACT, "text"): "Contact Details",
            (SectionRole.FOOTER, "text"): "Footer Text",
            (SectionRole.NAVIGATION, "url"): "Navigation Link",
        }

        # Try template match
        slot_type_hint = "text"  # default
        if (
            "image" in slot_id.lower()
            or "img" in slot_id.lower()
            or "photo" in slot_id.lower()
        ):
            slot_type_hint = "image"
        elif (
            "url" in slot_id.lower()
            or "link" in slot_id.lower()
            or "href" in slot_id.lower()
        ):
            slot_type_hint = "url"

        template_key = (section_role, slot_type_hint)
        if template_key in templates:
            return templates[template_key]

        # Fallback: clean up slot_id
        label = slot_id.replace("_", " ").replace("-", " ").title()
        if section_role != SectionRole.UNKNOWN:
            label = f"{section_role.value.replace('_', ' ').title()} — {label}"
        return label

    def _detect_repeatable_groups(
        self,
        fields: List[FormField],
        classified_sections: List[ClassifiedSection],
    ) -> List[RepeatableFieldGroup]:
        """
        Group fields from sections with repeat_instance_count > 1.
        """
        groups: List[RepeatableFieldGroup] = []

        # Find sections with repeats
        repeat_sections = {
            cs.section_role: cs
            for cs in classified_sections
            if cs.repeat_instance_count > 1
        }

        for role, section in repeat_sections.items():
            role_fields = [f for f in fields if f.section_role == role]
            if role_fields:
                group = RepeatableFieldGroup(
                    group_id=f"repeat_{role.value}",
                    section_role=role,
                    label=f"{role.value.replace('_', ' ').title()} Items",
                    instance_count=section.repeat_instance_count,
                    template_fields=role_fields,
                )
                groups.append(group)

        return groups
