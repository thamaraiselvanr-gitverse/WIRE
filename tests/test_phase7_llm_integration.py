"""
Phase 7 — Live LLM Integration Tests.

Tests that exercise GENUINE semantic ambiguity resolution through the
full guard → client → validate pipeline. Uses a mock LLM client that
returns structurally valid (but controlled) JSON responses, proving
the end-to-end path works correctly including:

1. Ambiguous sections that NO heuristic pattern would confidently resolve
2. Free-form intent text that doesn't match any keyword heuristic
3. Guard validation against real (possibly malformed) LLM responses
4. Retry-once-then-fail-closed behavior
5. Budget enforcement against live call paths

Also includes a marked @pytest.mark.live_llm category for tests that
hit the actual Gemini API (skipped by default, run with
`pytest -m live_llm` when GEMINI_API_KEY is set).
"""

import os
from typing import Optional

import pytest

from wire.schema.canonical import ComponentNode
from wire.schema.semantic_schema import (
    CLASSIFICATION_CONFIDENCE_THRESHOLD,
    ContentState,
    FormField,
    FormFieldType,
    SectionRole,
    WebsiteFormSchema,
)
from wire.semantic.intent_reconciler import IntentReconciler
from wire.semantic.llm_client import LLMClient
from wire.semantic.llm_guard import LLMGuard
from wire.semantic.placeholder_detector import PlaceholderDetector
from wire.semantic.section_classifier import SectionClassifier

# ── Helpers ─────────────────────────────────────────────────────────────


def _make_node(tag, attrs=None, text=None, children=None, slot_id=None):
    return ComponentNode(
        tag=tag,
        attributes=attrs or {},
        text_content=text,
        children=children or [],
        slot_id=slot_id,
    )


class MockLLMClient:
    """
    A mock LLM client that returns controlled responses.
    Allows tests to inject specific JSON responses and verify the
    full guard → client → validate pipeline.
    """

    def __init__(self, responses: list[Optional[dict]] = None):
        self._responses = list(responses) if responses else []
        self._call_log: list[dict] = []

    @property
    def is_available(self) -> bool:
        return True

    @property
    def call_count(self) -> int:
        return len(self._call_log)

    def generate_json(
        self,
        system_instruction: str,
        user_content: str,
        temperature: float = 0.1,
    ) -> Optional[dict]:
        self._call_log.append(
            {
                "system_instruction": system_instruction[:50],
                "user_content": user_content[:100],
            }
        )
        if self._responses:
            return self._responses.pop(0)
        return None


# ═══════════════════════════════════════════════════════════════════════
# 1. GENUINELY AMBIGUOUS SECTION CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════


class TestAmbiguousSectionClassification:
    """
    Tests with sections that have NO heuristic-resolvable signals —
    no <nav>/<footer> tags, no 'hero'/'contact' class names, no ARIA
    roles. These sections MUST go through the LLM path.
    """

    def _ambiguous_section(self):
        """A div with mixed signals — could be about, services, or portfolio."""
        return _make_node(
            "div",
            {"class": "main-content section-3"},
            children=[
                _make_node("h2", text="What We Do Best"),
                _make_node(
                    "div",
                    {"class": "grid-layout"},
                    children=[
                        _make_node(
                            "div",
                            {"class": "item"},
                            children=[
                                _make_node("h3", text="UI Design"),
                                _make_node("p", text="Crafting beautiful interfaces"),
                            ],
                        ),
                        _make_node(
                            "div",
                            {"class": "item"},
                            children=[
                                _make_node("h3", text="Web Development"),
                                _make_node(
                                    "p", text="Building scalable web applications"
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )

    def _deliberately_unclassifiable(self):
        """A section with absolutely no semantic signals."""
        return _make_node(
            "div",
            {"class": "block-7 fade-in"},
            children=[
                _make_node(
                    "div",
                    {"class": "inner"},
                    children=[
                        _make_node("span", text="..."),
                    ],
                ),
            ],
        )

    def test_ambiguous_section_llm_resolves_correctly(self):
        """LLM correctly classifies an ambiguous section as SERVICES."""
        mock_client = MockLLMClient(
            responses=[
                {
                    "section_role": "services",
                    "confidence": 0.88,
                    "reasoning": "Grid layout with service descriptions",
                }
            ]
        )
        guard = LLMGuard(llm_client=mock_client)
        classifier = SectionClassifier(guard)

        root = _make_node("div", children=[self._ambiguous_section()])
        result = classifier.classify_tree(root)

        assert len(result) == 1
        assert result[0].section_role == SectionRole.SERVICES
        assert result[0].confidence == 0.88
        assert result[0].is_heuristic is False
        assert mock_client.call_count >= 1

    def test_ambiguous_section_llm_returns_unknown_below_threshold(self):
        """LLM returns low confidence → section stays UNKNOWN."""
        mock_client = MockLLMClient(
            responses=[
                {
                    "section_role": "services",
                    "confidence": 0.45,
                    "reasoning": "Maybe services but unclear",
                }
            ]
        )
        guard = LLMGuard(llm_client=mock_client)
        classifier = SectionClassifier(guard)

        root = _make_node("div", children=[self._ambiguous_section()])
        result = classifier.classify_tree(root)

        assert len(result) == 1
        # validate_classification returns None for confidence < threshold,
        # so the classifier should fall to UNKNOWN
        assert result[0].section_role == SectionRole.UNKNOWN

    def test_unclassifiable_section_llm_returns_unknown(self):
        """LLM correctly returns UNKNOWN for genuinely unclassifiable content."""
        mock_client = MockLLMClient(
            responses=[
                {
                    "section_role": "unknown",
                    "confidence": 0.30,
                    "reasoning": "No identifiable content pattern",
                }
            ]
        )
        guard = LLMGuard(llm_client=mock_client)
        classifier = SectionClassifier(guard)

        root = _make_node("div", children=[self._deliberately_unclassifiable()])
        result = classifier.classify_tree(root)

        assert len(result) == 1
        assert result[0].section_role == SectionRole.UNKNOWN
        assert result[0].confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD

    def test_heuristic_still_bypasses_llm(self):
        """A <nav> tag should still classify via heuristic, never hitting LLM."""
        mock_client = MockLLMClient(responses=[])
        guard = LLMGuard(llm_client=mock_client)
        classifier = SectionClassifier(guard)

        root = _make_node(
            "div",
            children=[
                _make_node("nav", children=[_make_node("a", text="Home")]),
            ],
        )
        result = classifier.classify_tree(root)

        assert result[0].section_role == SectionRole.NAVIGATION
        assert result[0].is_heuristic is True
        assert mock_client.call_count == 0  # LLM never called


# ═══════════════════════════════════════════════════════════════════════
# 2. GENUINELY FREE-FORM INTENT EXTRACTION
# ═══════════════════════════════════════════════════════════════════════


class TestFreeFormIntentExtraction:
    """
    Tests with intent text that does NOT match keyword heuristics.
    These must go through the LLM path to produce meaningful results.
    """

    def test_complex_intent_no_keywords(self):
        """Intent that doesn't contain any keyword heuristic triggers."""
        mock_client = MockLLMClient(
            responses=[
                {
                    "user_role_domain": "independent ceramics artist",
                    "sections_to_emphasize": ["portfolio", "about", "contact"],
                    "sections_to_deprioritize": [],
                    "sections_to_exclude": ["pricing", "blog_feed"],
                    "explicit_field_overrides": [],
                }
            ]
        )
        guard = LLMGuard(llm_client=mock_client)
        reconciler = IntentReconciler(guard)

        schema = WebsiteFormSchema(
            source_url="https://test.com",
            sections=[
                SectionRole.HERO,
                SectionRole.PORTFOLIO,
                SectionRole.PRICING,
                SectionRole.CONTACT,
            ],
            fields=[
                FormField(
                    field_id="hero_1",
                    slot_id="s1",
                    cids_node_path="root",
                    label="Hero",
                    field_type=FormFieldType.TEXT,
                    section_role=SectionRole.HERO,
                    required=True,
                ),
                FormField(
                    field_id="portfolio_1",
                    slot_id="s2",
                    cids_node_path="root",
                    label="Work",
                    field_type=FormFieldType.TEXT,
                    section_role=SectionRole.PORTFOLIO,
                    required=True,
                ),
                FormField(
                    field_id="pricing_1",
                    slot_id="s3",
                    cids_node_path="root",
                    label="Price",
                    field_type=FormFieldType.TEXT,
                    section_role=SectionRole.PRICING,
                    required=True,
                ),
                FormField(
                    field_id="contact_1",
                    slot_id="s4",
                    cids_node_path="root",
                    label="Contact",
                    field_type=FormFieldType.TEXT,
                    section_role=SectionRole.CONTACT,
                    required=True,
                ),
            ],
        )

        # This prompt has NO keyword matches for "portfolio", "pricing" etc
        result = reconciler.reconcile(
            schema,
            "I throw pots and fire them in a wood kiln. I want to display my "
            "finished pieces and let collectors reach me, but I definitely "
            "don't need any sort of rate card or journal entries.",
        )

        assert result.reconciliation_summary is not None
        assert mock_client.call_count >= 1

        # Pricing should be excluded (LLM extracted "pricing" from "rate card")
        pricing_fields = [
            f for f in result.fields if f.section_role == SectionRole.PRICING
        ]
        for f in pricing_fields:
            assert f.required is False

    def test_intent_llm_unavailable_falls_to_heuristic(self):
        """When LLM is unavailable, heuristic fallback still works."""
        mock_client = MockLLMClient(responses=[None])  # LLM returns None
        guard = LLMGuard(llm_client=mock_client)
        reconciler = IntentReconciler(guard)

        schema = WebsiteFormSchema(
            source_url="https://test.com",
            sections=[SectionRole.HERO, SectionRole.CONTACT],
            fields=[
                FormField(
                    field_id="hero_1",
                    slot_id="s1",
                    cids_node_path="root",
                    label="Hero",
                    field_type=FormFieldType.TEXT,
                    section_role=SectionRole.HERO,
                    required=True,
                ),
            ],
        )

        # This has a keyword match for "contact"
        result = reconciler.reconcile(schema, "I need a contact page for my business")
        assert isinstance(result, WebsiteFormSchema)
        # Should still produce a valid result via heuristic fallback
        assert result.reconciliation_summary is not None


# ═══════════════════════════════════════════════════════════════════════
# 3. LLM GUARD AGAINST REAL (POSSIBLY MALFORMED) LLM OUTPUT
# ═══════════════════════════════════════════════════════════════════════


class TestLLMGuardLiveValidation:
    """Guard validation against realistic LLM outputs, not just stubs."""

    def test_retry_on_first_malformed_response(self):
        """First response is malformed, second is valid → succeeds."""
        mock_client = MockLLMClient(
            responses=[
                {"bad_key": "not a valid response"},  # First attempt: malformed
                {
                    "section_role": "about",
                    "confidence": 0.85,
                    "reasoning": "Contains bio text",
                },  # Retry: valid
            ]
        )
        guard = LLMGuard(llm_client=mock_client)

        node = _make_node("div", {"class": "info"}, text="About our company")
        result = guard.call_classification(node, "root > div:nth-child(1)")

        assert result is not None
        assert result.section_role == SectionRole.ABOUT
        assert result.confidence == 0.85
        assert mock_client.call_count == 2  # First call + retry

    def test_fail_closed_after_two_malformed_responses(self):
        """Both attempts return malformed output → returns None."""
        mock_client = MockLLMClient(
            responses=[
                {"wrong": "structure"},
                {"also": "wrong"},
            ]
        )
        guard = LLMGuard(llm_client=mock_client)

        node = _make_node("div", text="Some content")
        result = guard.call_classification(node, "root > div:nth-child(1)")

        assert result is None
        assert mock_client.call_count == 2

    def test_llm_returns_none(self):
        """LLM client itself returns None → guard returns None."""
        mock_client = MockLLMClient(responses=[None, None])
        guard = LLMGuard(llm_client=mock_client)

        node = _make_node("div", text="Content")
        result = guard.call_classification(node, "root > div:nth-child(1)")

        assert result is None

    def test_placeholder_retry_succeeds(self):
        """Placeholder detection retries on malformed first response."""
        mock_client = MockLLMClient(
            responses=[
                {"bad": "output"},
                {"is_likely_placeholder": True, "confidence": 0.90},
            ]
        )
        guard = LLMGuard(llm_client=mock_client)

        result = guard.call_placeholder("Some generic text", "text")
        assert result is not None
        assert result.is_placeholder is True

    def test_intent_retry_succeeds(self):
        """Intent extraction retries on malformed first response."""
        mock_client = MockLLMClient(
            responses=[
                {"garbage": True},
                {
                    "user_role_domain": "photographer",
                    "sections_to_emphasize": ["portfolio"],
                    "sections_to_deprioritize": [],
                    "sections_to_exclude": [],
                    "explicit_field_overrides": [],
                },
            ]
        )
        guard = LLMGuard(llm_client=mock_client)

        result = guard.call_intent("I'm a photographer showcasing my work")
        assert result is not None
        assert result["user_role_domain"] == "photographer"

    def test_budget_enforcement_on_live_calls(self):
        """Call budget is enforced even when LLM client is available."""
        mock_client = MockLLMClient(
            responses=[
                {
                    "section_role": "hero",
                    "confidence": 0.90,
                    "reasoning": "Hero section",
                }
            ]
            * 10
        )

        guard = LLMGuard(max_calls_per_run=2, llm_client=mock_client)
        node = _make_node("div", text="Content")

        # First two calls should work (each call_classification uses 1 prepare call)
        guard.call_classification(node, "path1")
        guard.call_classification(node, "path2")

        # Third call should be rejected by budget
        r3 = guard.call_classification(node, "path3")
        assert r3 is None

    def test_no_client_returns_none(self):
        """Guard with no LLM client → all call_ methods return None."""
        guard = LLMGuard()  # No client
        node = _make_node("div", text="Test")

        assert guard.call_classification(node, "path") is None
        assert guard.call_placeholder("value", "text") is None
        assert guard.call_intent("some intent") is None


# ═══════════════════════════════════════════════════════════════════════
# 4. PLACEHOLDER DETECTION WITH LLM FALLBACK
# ═══════════════════════════════════════════════════════════════════════


class TestPlaceholderLLMFallback:
    """Placeholder detection for ambiguous content that Layer 1 can't resolve."""

    def test_ambiguous_text_llm_detects_placeholder(self):
        """Text that looks real but is actually stock/template content."""
        mock_client = MockLLMClient(
            responses=[{"is_likely_placeholder": True, "confidence": 0.85}]
        )
        guard = LLMGuard(llm_client=mock_client)
        detector = PlaceholderDetector(guard)

        # This text is ~15 chars, too short for "substantial_text_no_patterns"
        # but too long for "suspiciously_short_text" — Layer 1 inconclusive
        result = detector.evaluate_field("A nice company", FormFieldType.TEXT)
        assert result.is_placeholder is True
        assert result.content_state == ContentState.CONFIRMED_PLACEHOLDER

    def test_ambiguous_text_llm_confirms_real(self):
        """Text that's short but actually real content."""
        mock_client = MockLLMClient(
            responses=[{"is_likely_placeholder": False, "confidence": 0.90}]
        )
        guard = LLMGuard(llm_client=mock_client)
        detector = PlaceholderDetector(guard)

        result = detector.evaluate_field("Smith & Co Ltd", FormFieldType.TEXT)
        assert result.is_placeholder is False
        assert result.content_state == ContentState.CONFIRMED_REAL

    def test_layer1_still_bypasses_llm(self):
        """Known placeholder patterns bypass LLM entirely."""
        mock_client = MockLLMClient(responses=[])
        guard = LLMGuard(llm_client=mock_client)
        detector = PlaceholderDetector(guard)

        result = detector.evaluate_field(
            "Lorem ipsum dolor sit amet", FormFieldType.TEXT
        )
        assert result.is_placeholder is True
        assert mock_client.call_count == 0


# ═══════════════════════════════════════════════════════════════════════
# 5. LIVE GEMINI API TESTS (skipped by default)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.live_llm
class TestLiveGeminiAPI:
    """
    Tests against the actual Gemini API.
    Requires GEMINI_API_KEY to be set. Skipped by default.
    Run with: pytest -m live_llm tests/test_phase7_llm_integration.py
    """

    @pytest.fixture(autouse=True)
    def skip_without_api_key(self):
        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            pytest.skip("GEMINI_API_KEY not set — skipping live LLM tests")

    def test_live_classification_ambiguous_section(self):
        """Live LLM correctly classifies an ambiguous services section."""
        client = LLMClient()
        guard = LLMGuard(llm_client=client)
        classifier = SectionClassifier(guard)

        # Ambiguous section — no heuristic signals
        root = _make_node(
            "div",
            children=[
                _make_node(
                    "div",
                    {"class": "offerings-block"},
                    children=[
                        _make_node("h2", text="What We Offer"),
                        _make_node(
                            "div",
                            {"class": "item"},
                            children=[
                                _make_node("h3", text="Brand Strategy"),
                                _make_node(
                                    "p",
                                    text="We help define your brand identity and market position",
                                ),
                            ],
                        ),
                        _make_node(
                            "div",
                            {"class": "item"},
                            children=[
                                _make_node("h3", text="Visual Design"),
                                _make_node(
                                    "p",
                                    text="Creating cohesive visual systems for your brand",
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )

        result = classifier.classify_tree(root)
        assert len(result) == 1
        # LLM should classify this as SERVICES or FEATURE_GRID
        assert result[0].section_role in {
            SectionRole.SERVICES,
            SectionRole.FEATURE_GRID,
            SectionRole.PORTFOLIO,
        }
        assert result[0].confidence >= CLASSIFICATION_CONFIDENCE_THRESHOLD
        assert result[0].is_heuristic is False

    def test_live_intent_extraction_no_keywords(self):
        """Live LLM extracts intent from genuinely free-form text."""
        client = LLMClient()
        guard = LLMGuard(llm_client=client)

        result = guard.call_intent(
            "I throw pots and fire them in a wood kiln. I want to display my "
            "finished pieces and let collectors reach me, but I definitely "
            "don't need any sort of rate card or journal entries."
        )

        assert result is not None
        assert result.get("user_role_domain") is not None
        # Should extract emphasis on portfolio/about/contact equivalent
        # and exclusion of pricing/blog equivalent
        assert len(result.get("sections_to_exclude", [])) >= 1

    def test_live_placeholder_detection(self):
        """Live LLM detects that generic text is placeholder content."""
        client = LLMClient()
        guard = LLMGuard(llm_client=client)

        result = guard.call_placeholder(
            "A great company with a great team doing great things", "text"
        )

        assert result is not None
        assert result.is_placeholder is True
