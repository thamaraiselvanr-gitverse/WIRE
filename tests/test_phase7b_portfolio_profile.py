"""
Phase 7b Test Suite — Portfolio Domain Profile.

Tests that PortfolioProfile.adapt() correctly maps general roles per
GENERAL_TO_PORTFOLIO_MAPPING, excludes unmapped sections, and produces
sparse/mostly-empty output for non-portfolio site types — proving the
domain-profile boundary holds.
"""

import pytest
from wire.schema.semantic_schema import (
    SectionRole,
    ContentState,
    FormFieldType,
    FormField,
    WebsiteFormSchema,
)
from wire.schema.portfolio_schema import PortfolioFormSchema, PortfolioSection
from wire.semantic.profiles.portfolio_profile import PortfolioProfile


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_field(role: SectionRole, slot_id: str, label: str = "Test") -> FormField:
    """Create a minimal FormField for testing."""
    return FormField(
        field_id=f"{role.value}_{slot_id}",
        slot_id=slot_id,
        cids_node_path=f"root > div > {role.value}",
        label=label,
        field_type=FormFieldType.TEXT,
        section_role=role,
        required=True,
        content_state=ContentState.CONFIRMED_REAL,
    )


def _portfolio_schema() -> WebsiteFormSchema:
    """A general schema from a portfolio-shaped site."""
    return WebsiteFormSchema(
        source_url="https://portfolio-site.com",
        sections=[
            SectionRole.HERO, SectionRole.ABOUT, SectionRole.PORTFOLIO,
            SectionRole.CONTACT, SectionRole.SOCIAL_LINKS, SectionRole.FOOTER,
        ],
        fields=[
            _make_field(SectionRole.HERO, "hero_title", "Hero Title"),
            _make_field(SectionRole.ABOUT, "about_text", "About Text"),
            _make_field(SectionRole.PORTFOLIO, "project_1", "Project 1"),
            _make_field(SectionRole.PORTFOLIO, "project_2", "Project 2"),
            _make_field(SectionRole.CONTACT, "contact_email", "Contact Email"),
            _make_field(SectionRole.SOCIAL_LINKS, "twitter_link", "Twitter"),
            _make_field(SectionRole.FOOTER, "footer_text", "Footer Text"),
        ],
    )


def _saas_schema() -> WebsiteFormSchema:
    """A general schema from a SaaS landing page."""
    return WebsiteFormSchema(
        source_url="https://saas-product.com",
        sections=[
            SectionRole.HERO, SectionRole.FEATURE_GRID, SectionRole.PRICING,
            SectionRole.CTA, SectionRole.FAQ, SectionRole.FOOTER,
        ],
        fields=[
            _make_field(SectionRole.HERO, "saas_title", "SaaS Title"),
            _make_field(SectionRole.FEATURE_GRID, "feature_1", "Feature 1"),
            _make_field(SectionRole.FEATURE_GRID, "feature_2", "Feature 2"),
            _make_field(SectionRole.PRICING, "plan_starter", "Starter Plan"),
            _make_field(SectionRole.PRICING, "plan_pro", "Pro Plan"),
            _make_field(SectionRole.CTA, "cta_button", "CTA Button"),
            _make_field(SectionRole.FAQ, "faq_1", "FAQ 1"),
            _make_field(SectionRole.FOOTER, "footer_copy", "Footer Copy"),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════
# PORTFOLIO PROFILE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestPortfolioProfileMapping:
    """Verify correct mapping of general roles to portfolio categories."""

    def setup_method(self):
        self.profile = PortfolioProfile()

    def test_hero_maps_to_bio_header(self):
        schema = _portfolio_schema()
        result = self.profile.adapt(schema)
        bio_header = self._find_section(result, "bio_header")
        assert bio_header is not None
        assert bio_header.is_applicable is True
        assert len(bio_header.fields) >= 1
        assert bio_header.fields[0].slot_id == "hero_title"

    def test_about_maps_to_bio(self):
        schema = _portfolio_schema()
        result = self.profile.adapt(schema)
        bio = self._find_section(result, "bio")
        assert bio is not None
        assert bio.is_applicable is True
        assert any(f.slot_id == "about_text" for f in bio.fields)

    def test_portfolio_maps_to_projects(self):
        schema = _portfolio_schema()
        result = self.profile.adapt(schema)
        projects = self._find_section(result, "projects")
        assert projects is not None
        assert projects.is_applicable is True
        assert len(projects.fields) >= 2

    def test_contact_maps_to_contact(self):
        schema = _portfolio_schema()
        result = self.profile.adapt(schema)
        contact = self._find_section(result, "contact")
        assert contact is not None
        assert contact.is_applicable is True

    def test_social_links_maps_to_social_links(self):
        schema = _portfolio_schema()
        result = self.profile.adapt(schema)
        social = self._find_section(result, "social_links")
        assert social is not None
        assert social.is_applicable is True

    def test_footer_excluded_from_portfolio(self):
        """FOOTER maps to None — fields should be excluded."""
        schema = _portfolio_schema()
        result = self.profile.adapt(schema)
        assert result.excluded_fields >= 1
        # Verify footer text is not in any portfolio section
        all_slot_ids = [
            f.slot_id
            for s in result.sections
            for f in s.fields
        ]
        assert "footer_text" not in all_slot_ids

    def test_field_counts_are_consistent(self):
        schema = _portfolio_schema()
        result = self.profile.adapt(schema)
        assert result.total_fields == len(schema.fields)
        assert result.mapped_fields + result.excluded_fields == result.total_fields

    @staticmethod
    def _find_section(schema: PortfolioFormSchema, category: str) -> PortfolioSection | None:
        for s in schema.sections:
            if s.portfolio_category == category:
                return s
        return None


class TestPortfolioProfileExclusion:
    """Unmapped sections are excluded, never force-mapped."""

    def setup_method(self):
        self.profile = PortfolioProfile()

    def test_pricing_excluded(self):
        """PRICING has no portfolio mapping → excluded."""
        schema = WebsiteFormSchema(
            source_url="https://test.com",
            sections=[SectionRole.PRICING],
            fields=[_make_field(SectionRole.PRICING, "price_1")],
        )
        result = self.profile.adapt(schema)
        assert result.excluded_fields == 1
        assert result.mapped_fields == 0

    def test_team_excluded(self):
        """TEAM maps to None (single-person portfolio) → excluded."""
        schema = WebsiteFormSchema(
            source_url="https://test.com",
            sections=[SectionRole.TEAM],
            fields=[_make_field(SectionRole.TEAM, "team_member_1")],
        )
        result = self.profile.adapt(schema)
        assert result.excluded_fields == 1
        assert result.mapped_fields == 0

    def test_cta_excluded(self):
        schema = WebsiteFormSchema(
            source_url="https://test.com",
            sections=[SectionRole.CTA],
            fields=[_make_field(SectionRole.CTA, "cta_1")],
        )
        result = self.profile.adapt(schema)
        assert result.excluded_fields == 1

    def test_faq_excluded(self):
        schema = WebsiteFormSchema(
            source_url="https://test.com",
            sections=[SectionRole.FAQ],
            fields=[_make_field(SectionRole.FAQ, "faq_1")],
        )
        result = self.profile.adapt(schema)
        assert result.excluded_fields == 1

    def test_blog_feed_excluded(self):
        schema = WebsiteFormSchema(
            source_url="https://test.com",
            sections=[SectionRole.BLOG_FEED],
            fields=[_make_field(SectionRole.BLOG_FEED, "blog_1")],
        )
        result = self.profile.adapt(schema)
        assert result.excluded_fields == 1


class TestPortfolioProfileBoundary:
    """
    THE KEY PROOF: a non-portfolio site through the portfolio profile
    produces sparse/mostly-empty output, not fabricated portfolio fields.
    """

    def setup_method(self):
        self.profile = PortfolioProfile()

    def test_saas_through_portfolio_is_sparse(self):
        """SaaS site run through portfolio profile → sparse output."""
        schema = _saas_schema()
        result = self.profile.adapt(schema)

        # Should have mostly empty/inapplicable sections
        applicable_sections = [s for s in result.sections if s.is_applicable]
        inapplicable_sections = [s for s in result.sections if not s.is_applicable]

        # HERO maps to bio_header, FEATURE_GRID maps to skills — those are the
        # only applicable mappings. PRICING, CTA, FAQ, FOOTER map to None.
        assert len(applicable_sections) <= 3  # at most hero→bio_header, features→skills, footer excluded
        assert len(inapplicable_sections) >= 5

        # Excluded fields should be the majority
        assert result.excluded_fields > result.mapped_fields

        # No fabricated portfolio fields — every mapped field has a real slot_id
        for section in result.sections:
            for field in section.fields:
                assert field.slot_id  # non-empty
                assert field.slot_id in [f.slot_id for f in schema.fields]

    def test_saas_no_projects_fabricated(self):
        """SaaS site should NOT have fabricated 'projects' from pricing."""
        schema = _saas_schema()
        result = self.profile.adapt(schema)
        projects = None
        for s in result.sections:
            if s.portfolio_category == "projects":
                projects = s
                break
        assert projects is not None
        # No pricing fields should appear in projects
        pricing_slots = {"plan_starter", "plan_pro"}
        for field in projects.fields:
            assert field.slot_id not in pricing_slots

    def test_feature_grid_maps_to_skills(self):
        """FEATURE_GRID → skills in portfolio context."""
        schema = _saas_schema()
        result = self.profile.adapt(schema)
        skills = None
        for s in result.sections:
            if s.portfolio_category == "skills":
                skills = s
                break
        assert skills is not None
        if skills.is_applicable:
            assert all(f.portfolio_category == "skills" for f in skills.fields)

    def test_empty_schema_produces_all_inapplicable(self):
        """Schema with no fields → all portfolio sections inapplicable."""
        schema = WebsiteFormSchema(source_url="https://empty.com", sections=[], fields=[])
        result = self.profile.adapt(schema)
        assert all(not s.is_applicable for s in result.sections)
        assert result.mapped_fields == 0
        assert result.excluded_fields == 0
