"""
Portfolio Profile — Domain-Specific Adapter (Phase 7b).

Maps a general-purpose WebsiteFormSchema (Phase 7a output) into the
portfolio domain model (PortfolioFormSchema).  This class is the ONLY
place portfolio-specific assumptions live; the upstream semantic layer
is intentionally unaware of any domain mapping.

Design rules
─────────────
• READ-ONLY consumer of the CIDS tree — never mutates Phase 1-6 data.
• Fail-closed: unmapped sections are tracked, never silently dropped.
• Every PortfolioField carries a traceable ``slot_id`` — no fabrication.
"""

from __future__ import annotations

from typing import ClassVar, Dict, List, Optional

import structlog

from wire.schema.portfolio_schema import (
    PortfolioField,
    PortfolioFormSchema,
    PortfolioSection,
)
from wire.schema.semantic_schema import (
    FormField,
    SectionRole,
    WebsiteFormSchema,
)

logger = structlog.get_logger(__name__)


class PortfolioProfile:
    """Maps a general ``WebsiteFormSchema`` into a ``PortfolioFormSchema``.

    Class-level constants define the *entire* mapping surface between the
    general section taxonomy (``SectionRole``) and the portfolio domain.
    Adding / removing a mapping here is the **only** change needed to
    alter portfolio behaviour.
    """

    # ── SectionRole → portfolio category (or None = excluded) ───────────

    GENERAL_TO_PORTFOLIO_MAPPING: ClassVar[Dict[SectionRole, Optional[str]]] = {
        SectionRole.HERO: "bio_header",
        SectionRole.ABOUT: "bio",
        SectionRole.PORTFOLIO: "projects",
        SectionRole.TEAM: None,  # not applicable to single-person portfolio
        SectionRole.TESTIMONIALS: "testimonials",
        SectionRole.CONTACT: "contact",
        SectionRole.SOCIAL_LINKS: "social_links",
        SectionRole.NAVIGATION: None,  # structural, not content
        SectionRole.FOOTER: None,  # structural, not content
        SectionRole.SIDEBAR: None,
        SectionRole.MEDIA_GALLERY: "projects",  # gallery maps to projects in portfolio context
        SectionRole.CTA: None,
        SectionRole.FAQ: None,
        SectionRole.BLOG_FEED: None,
        SectionRole.FEATURE_GRID: "skills",  # features → skills in portfolio context
        SectionRole.PRICING: None,
        SectionRole.SERVICES: "services",  # services maps to services in portfolio
        SectionRole.UNKNOWN: None,
    }

    # ── Ordered portfolio category metadata ─────────────────────────────

    PORTFOLIO_CATEGORIES: ClassVar[Dict[str, str]] = {
        "bio_header": "Header & Title",
        "bio": "About Me",
        "skills": "Skills & Expertise",
        "projects": "Projects & Work",
        "services": "Services",
        "testimonials": "Testimonials",
        "contact": "Contact Information",
        "social_links": "Social Media Links",
    }

    # ── Public API ──────────────────────────────────────────────────────

    def adapt(self, general_schema: WebsiteFormSchema) -> PortfolioFormSchema:
        """Map a general ``WebsiteFormSchema`` to a ``PortfolioFormSchema``.

        Steps
        ─────
        1. Map each ``FormField`` via ``GENERAL_TO_PORTFOLIO_MAPPING``.
        2. Map each ``RepeatableFieldGroup``'s template fields the same way.
        3. Group mapped fields into ``PortfolioSection`` objects.
        4. Mark unmapped categories as ``is_applicable=False``.
        5. Track unmapped general sections (no fields AND no mapping).
        6. Log a mapping summary.

        Parameters
        ----------
        general_schema:
            The site-type-agnostic form schema produced by Phase 7a.

        Returns
        -------
        PortfolioFormSchema
            The portfolio-domain-specific output consumed by the UI layer.
        """
        mapped_fields: int = 0
        excluded_fields: int = 0

        # category_key → list[PortfolioField]
        category_fields: Dict[str, List[PortfolioField]] = {
            cat: [] for cat in self.PORTFOLIO_CATEGORIES
        }

        # ── 1. Map individual fields ────────────────────────────────────
        for field in general_schema.fields:
            portfolio_cat = self._resolve_category(field.section_role)
            if portfolio_cat is not None:
                category_fields[portfolio_cat].append(
                    self._to_portfolio_field(field, portfolio_cat),
                )
                mapped_fields += 1
            else:
                excluded_fields += 1

        # ── 2. Map repeatable-group template fields ─────────────────────
        for group in general_schema.repeatable_groups:
            portfolio_cat = self._resolve_category(group.section_role)
            if portfolio_cat is None:
                continue
            for tmpl_field in group.template_fields:
                category_fields[portfolio_cat].append(
                    self._to_portfolio_field(tmpl_field, portfolio_cat),
                )
                mapped_fields += 1

        # ── 3. Build PortfolioSection objects ───────────────────────────
        sections: List[PortfolioSection] = []
        for cat_key, display_name in self.PORTFOLIO_CATEGORIES.items():
            fields = category_fields[cat_key]
            sections.append(
                PortfolioSection(
                    portfolio_category=cat_key,
                    display_name=display_name,
                    fields=fields,
                    is_applicable=len(fields) > 0,
                )
            )

        # ── 4. Track unmapped general sections ──────────────────────────
        # A section role is "unmapped" if it has no mapping entry at all
        # (i.e. not present in GENERAL_TO_PORTFOLIO_MAPPING).  Roles that
        # map to None are *excluded*, not *unmapped*.
        section_roles_in_schema = set(general_schema.sections)
        unmapped_general_sections: List[str] = [
            role.value
            for role in section_roles_in_schema
            if role not in self.GENERAL_TO_PORTFOLIO_MAPPING
        ]

        total_fields = mapped_fields + excluded_fields

        # ── 5. Log summary ──────────────────────────────────────────────
        logger.info(
            "portfolio_profile.adapt_complete",
            source_url=general_schema.source_url,
            total_fields=total_fields,
            mapped_fields=mapped_fields,
            excluded_fields=excluded_fields,
            sections_with_fields=sum(1 for s in sections if s.is_applicable),
            unmapped_general_sections=unmapped_general_sections,
        )

        return PortfolioFormSchema(
            source_url=general_schema.source_url,
            sections=sections,
            unmapped_general_sections=unmapped_general_sections,
            total_fields=total_fields,
            mapped_fields=mapped_fields,
            excluded_fields=excluded_fields,
        )

    # ── Internal helpers ────────────────────────────────────────────────

    def _resolve_category(self, role: SectionRole) -> Optional[str]:
        """Look up the portfolio category for a ``SectionRole``.

        Returns ``None`` when the role explicitly maps to ``None`` (excluded)
        or when the role has no entry in the mapping (unknown).
        """
        return self.GENERAL_TO_PORTFOLIO_MAPPING.get(role)

    @staticmethod
    def _to_portfolio_field(
        field: FormField,
        portfolio_category: str,
    ) -> PortfolioField:
        """Convert a general ``FormField`` to a ``PortfolioField``."""
        return PortfolioField(
            field_id=field.field_id,
            slot_id=field.slot_id,
            portfolio_category=portfolio_category,
            label=field.label,
            field_type=field.field_type.value,
            required=field.required,
            original_value=field.original_value,
            content_state=field.content_state.value,
            validation_rules=field.validation_rules,
        )
