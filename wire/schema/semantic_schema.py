"""
Semantic Schema — General-Purpose Website Section Classification & Form Schema Models.

Phase 7a: Site-type-agnostic data models for section classification,
placeholder detection, and form schema compilation. These models are
consumed by all domain profiles (Phase 7b) and are intentionally free
of any site-type-specific assumptions.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Confidence Thresholds (single source of truth) ──────────────────────────

CLASSIFICATION_CONFIDENCE_THRESHOLD: float = 0.80
PLACEHOLDER_CONFIDENCE_THRESHOLD: float = 0.65


# ── Enums ───────────────────────────────────────────────────────────────────

class SectionRole(str, Enum):
    """
    General-purpose website section taxonomy.
    
    Intentionally NOT portfolio-specific. PORTFOLIO here means "a section
    showcasing work/output" (could appear on a photographer's site, an
    agency's site, or a freelancer's site) — it is a content-shape
    classification, not a declaration that the whole site is a "portfolio site."
    """
    HERO = "hero"
    NAVIGATION = "navigation"
    ABOUT = "about"
    SERVICES = "services"
    PORTFOLIO = "portfolio"
    TESTIMONIALS = "testimonials"
    TEAM = "team"
    PRICING = "pricing"
    CONTACT = "contact"
    FOOTER = "footer"
    SIDEBAR = "sidebar"
    MEDIA_GALLERY = "media_gallery"
    CTA = "cta"
    FAQ = "faq"
    BLOG_FEED = "blog_feed"
    FEATURE_GRID = "feature_grid"
    SOCIAL_LINKS = "social_links"
    UNKNOWN = "unknown"


class ContentState(str, Enum):
    """Content placeholder vs. real content classification."""
    CONFIRMED_PLACEHOLDER = "confirmed_placeholder"
    CONFIRMED_REAL = "confirmed_real"
    NEEDS_USER_CONFIRMATION = "needs_user_confirmation"


class FormFieldType(str, Enum):
    """General form field types for schema compilation."""
    TEXT = "text"
    TEXTAREA = "textarea"
    IMAGE = "image"
    URL = "url"
    COLOR = "color"
    REPEATABLE_GROUP = "repeatable_group"


# ── Classification Models ───────────────────────────────────────────────────

class ClassifiedSection(BaseModel):
    """Result of classifying a CIDS subtree into a known content role."""
    node_path: str
    section_role: SectionRole
    confidence: float
    reasoning: str = ""
    is_heuristic: bool = False
    child_count: int = 0
    repeat_instance_count: int = 0


# ── Placeholder Detection Models ───────────────────────────────────────────

class PlaceholderResult(BaseModel):
    """Result of evaluating whether a field's content is placeholder or real."""
    is_placeholder: bool
    confidence: float
    content_state: ContentState
    signals: List[str] = Field(default_factory=list)
    replacement_slot_type: Optional[str] = None


# ── Form Schema Models ─────────────────────────────────────────────────────

class FormField(BaseModel):
    """
    A single fillable field derived from a slot_id in the CIDS tree.
    
    General-purpose — not portfolio-typed. The section_role comes from the
    classifier; the field_type comes from the existing InputBlueprint
    slot constraint; the content_state comes from the placeholder detector.
    """
    field_id: str
    slot_id: str
    cids_node_path: str
    label: str
    field_type: FormFieldType
    section_role: SectionRole
    required: bool = False
    content_state: ContentState = ContentState.NEEDS_USER_CONFIRMATION
    original_value: Optional[str] = None
    classification_confidence: float = 0.0
    placeholder_confidence: float = 0.0
    validation_rules: Dict[str, Any] = Field(default_factory=dict)


class RepeatableFieldGroup(BaseModel):
    """
    A group of structurally identical fields (e.g. repeated team members,
    pricing tiers, portfolio pieces, feature cards). Applies generally —
    not assumed to be "projects" specifically.
    """
    group_id: str
    section_role: SectionRole
    label: str
    instance_count: int
    template_fields: List[FormField] = Field(default_factory=list)


class WebsiteFormSchema(BaseModel):
    """
    General, site-type-agnostic form schema output of Phase 7a.
    
    Renamed from the original PortfolioFormSchema — this is the primary
    output of the semantic interpretation layer, consumed by domain
    profiles (Phase 7b) to produce domain-specific form schemas.
    """
    schema_version: str = "1.0"
    source_url: str
    sections: List[SectionRole] = Field(default_factory=list)
    fields: List[FormField] = Field(default_factory=list)
    repeatable_groups: List[RepeatableFieldGroup] = Field(default_factory=list)
    unsupported_requests: List[str] = Field(default_factory=list)
    reconciliation_summary: Optional[str] = None
    needs_confirmation: List[str] = Field(default_factory=list)
    read_only_sections: List[str] = Field(default_factory=list)
