"""
Portfolio Form Schema — Domain-Specific Output (Phase 7b).

This is the portfolio-specific artifact produced by PortfolioProfile.adapt().
It maps general WebsiteFormSchema sections/fields into the portfolio domain
model (name, bio, skills, projects, experience, education, social links).

This file is the ONLY place portfolio-specific field definitions live.
The general semantic layer (Phase 7a) is intentionally unaware of these models.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PortfolioField(BaseModel):
    """A portfolio-specific field mapped from a general FormField."""

    field_id: str
    slot_id: str
    portfolio_category: str
    label: str
    field_type: str
    required: bool = False
    original_value: Optional[str] = None
    content_state: str = "needs_user_confirmation"
    validation_rules: Dict[str, Any] = Field(default_factory=dict)


class PortfolioSection(BaseModel):
    """A portfolio-specific section grouping mapped fields."""

    portfolio_category: str
    display_name: str
    fields: List[PortfolioField] = Field(default_factory=list)
    is_applicable: bool = True


class PortfolioFormSchema(BaseModel):
    """
    Portfolio domain-specific form schema — Phase 7b output artifact.

    Consumed by the eventual portfolio form-rendering UI. Produced by
    PortfolioProfile.adapt() from a general WebsiteFormSchema.
    """

    schema_version: str = "1.0"
    source_url: str
    sections: List[PortfolioSection] = Field(default_factory=list)
    unmapped_general_sections: List[str] = Field(default_factory=list)
    total_fields: int = 0
    mapped_fields: int = 0
    excluded_fields: int = 0
