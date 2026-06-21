from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Literal, Union, Annotated, Any
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

class UrlValue(BaseSubmittedValue):
    type: Literal["url"] = "url"
    value: str

class RepeatableGroupValue(BaseSubmittedValue):
    type: Literal["repeatable_group"] = "repeatable_group"
    instances: List[Dict[str, 'SubmittedValue']]

# Discriminator pattern for JSON serialization and parsing
SubmittedValue = Annotated[
    Union[TextValue, ImageValue, UrlValue, RepeatableGroupValue],
    Field(discriminator="type")
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
    type: Literal["text", "image", "url"]
    value: str  # text/url literal or stored image path/URL

class ContentSubstitution(BaseModel):
    field_id: str
    slot_id: str
    cids_node_path: str
    section_role: SectionRole
    original_value: Optional[str] = None
    substituted_value: SubstitutedValueRef
    substitution_type: Literal["text_replace", "image_replace", "repeatable_instance_add"]

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
