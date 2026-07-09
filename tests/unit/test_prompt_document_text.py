from wire.generation.transformation_prompt_generator import (
    TransformationPromptGenerator,
)
from wire.schema.semantic_schema import SectionRole
from wire.schema.submission_schema import ContentSubstitution, SubstitutedValueRef


def _sub(field_id, ref_type, value, substitution_type, extracted_text=None):
    return ContentSubstitution(
        field_id=field_id,
        slot_id=f"slot_{field_id}",
        cids_node_path="root > div",
        section_role=SectionRole.ABOUT,
        substituted_value=SubstitutedValueRef(
            type=ref_type, value=value, extracted_text=extracted_text
        ),
        substitution_type=substitution_type,
    )


def test_document_extracted_text_surfaced_to_llm_payload():
    subs = [
        _sub(
            "bio",
            "document",
            "assets/user_uploads/cv.pdf",
            "document_replace",
            extracted_text="Jane Doe — 10 years designing brand systems.",
        ),
        _sub("headline", "text", "New headline", "text_replace"),
    ]
    data = TransformationPromptGenerator._build_subs_data(subs)
    by_field = {d["field_id"]: d for d in data}

    # The document's extracted text is included (not just the opaque file path).
    assert "document_text" in by_field["bio"]
    assert "brand systems" in by_field["bio"]["document_text"]
    assert by_field["bio"]["value_kind"] == "document"
    # Plain text substitutions have no document_text.
    assert "document_text" not in by_field["headline"]


def test_document_text_is_truncated():
    long_text = "x" * 10000
    subs = [
        _sub("bio", "document", "p.pdf", "document_replace", extracted_text=long_text)
    ]
    data = TransformationPromptGenerator._build_subs_data(subs)
    assert (
        len(data[0]["document_text"])
        == TransformationPromptGenerator._MAX_DOC_TEXT_CHARS
    )
