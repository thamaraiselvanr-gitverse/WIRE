from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from wire.schema.semantic_schema import SectionRole


class BaseSubmittedValue(BaseModel):
    pass


class TextValue(BaseSubmittedValue):
    type: Literal["text"] = "text"
    value: str


class ImageValue(BaseSubmittedValue):
    type: Literal["image"] = "image"
    value: str  # Base64 encoded raw bytes
    original_filename: str
    content_type: str
    # Understanding derived during ingestion (populated in place).
    alt_text: Optional[str] = None
    dominant_color: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class VideoValue(BaseSubmittedValue):
    type: Literal["video"] = "video"
    value: str  # Base64 encoded raw bytes
    original_filename: str
    content_type: str


class AudioValue(BaseSubmittedValue):
    type: Literal["audio"] = "audio"
    value: str  # Base64 encoded raw bytes
    original_filename: str
    content_type: str


class DocumentValue(BaseSubmittedValue):
    type: Literal["document"] = "document"
    value: str  # Base64 encoded raw bytes (replaced with a stored path on ingest)
    original_filename: str
    content_type: str
    # Text extracted from the document during ingestion (PDF/DOCX/text families).
    extracted_text: Optional[str] = None
    # Structured understanding derived from the extracted text (title, headings,
    # summary, emails, urls, counts) so the right slot gets the right piece.
    extracted_structure: Optional[Dict[str, Any]] = None


class UrlValue(BaseSubmittedValue):
    type: Literal["url"] = "url"
    value: str


class RepeatableGroupValue(BaseSubmittedValue):
    type: Literal["repeatable_group"] = "repeatable_group"
    instances: List[Dict[str, "SubmittedValue"]]


# Discriminator pattern for JSON serialization and parsing
SubmittedValue = Annotated[
    Union[
        TextValue,
        ImageValue,
        VideoValue,
        AudioValue,
        DocumentValue,
        UrlValue,
        RepeatableGroupValue,
    ],
    Field(discriminator="type"),
]

RepeatableGroupValue.model_rebuild()


class SubmissionPayload(BaseModel):
    run_id: str
    field_values: Dict[str, SubmittedValue] = Field(default_factory=dict)


class ValidationItem(BaseModel):
    field_id: str
    message: str


class ValidationSummary(BaseModel):
    is_valid: bool
    hard_failures: List[ValidationItem] = Field(default_factory=list)
    soft_warnings: List[ValidationItem] = Field(default_factory=list)
    successes: List[ValidationItem] = Field(default_factory=list)


class SubstitutedValueRef(BaseModel):
    type: Literal["text", "image", "video", "audio", "document", "url"]
    value: str  # text/url literal or stored media/document path/URL
    # Optional text extracted from an uploaded document (e.g. PDF/DOCX),
    # available to the transformation prompt for content-aware substitution.
    extracted_text: Optional[str] = None
    # Understanding derived from an uploaded image, so the transformation prompt
    # can set accessible alt text and theme the slot to the image.
    alt_text: Optional[str] = None
    dominant_color: Optional[str] = None
    # Intrinsic pixel dimensions of an uploaded image, used by the layout-safety
    # check to flag aspect-ratio shifts that would distort the slot.
    width: Optional[int] = None
    height: Optional[int] = None
    # Structured fields (title/summary/headings/...) from an uploaded document.
    structure: Optional[Dict[str, Any]] = None


class ContentSubstitution(BaseModel):
    field_id: str
    slot_id: str
    cids_node_path: str
    section_role: SectionRole
    original_value: Optional[str] = None
    substituted_value: SubstitutedValueRef
    substitution_type: Literal[
        "text_replace",
        "image_replace",
        "media_replace",
        "document_replace",
        "repeatable_instance_add",
    ]


class TransformationPrompt(BaseModel):
    source_url: str
    design_summary: str
    substitutions: List[ContentSubstitution] = Field(default_factory=list)
    substitution_summary: str
    preserved_structure_notes: List[str] = Field(default_factory=list)


class SubmissionResult(BaseModel):
    success: bool
    validation_report: ValidationSummary
    transformation_prompt: Optional[TransformationPrompt] = None
