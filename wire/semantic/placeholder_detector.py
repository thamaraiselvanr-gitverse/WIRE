"""
Placeholder Detector — Multi-Signal Content Analysis.

Detects placeholder vs. real content using a two-layer approach:
Layer 1 (deterministic pattern matching) runs first with no LLM cost;
Layer 2 (LLM-assisted) only fires if Layer 1 is inconclusive.
Images use Layer 1 only — inconclusive defaults to NEEDS_USER_CONFIRMATION.
"""

import re
from typing import List, Optional

import structlog

from wire.schema.semantic_schema import (
    PLACEHOLDER_CONFIDENCE_THRESHOLD,
    ContentState,
    FormFieldType,
    PlaceholderResult,
)
from wire.semantic.llm_guard import LLMGuard

logger = structlog.get_logger(__name__)

# ── Layer 1: Deterministic Patterns ─────────────────────────────────────

_TEXT_PLACEHOLDER_PATTERNS = [
    r"lorem\s+ipsum",
    r"dolor\s+sit\s+amet",
    r"placeholder",
    r"your\s+name\s+here",
    r"your\s+email",
    r"john\s+doe",
    r"jane\s+doe",
    r"example\.com",
    r"sample\s+text",
    r"coming\s+soon",
    r"enter\s+your",
    r"type\s+here",
    r"your\s+.*\s+here",
    r"insert\s+.*\s+here",
    r"add\s+your",
    r"write\s+your",
    r"\[your\s+",
    r"xxx+",
]

_IMAGE_PLACEHOLDER_HOSTS = [
    "placeholder.com",
    "picsum.photos",
    "unsplash.com/random",
    "via.placeholder",
    "dummyimage.com",
    "placehold.it",
    "placekitten.com",
    "lorempixel.com",
    "fakeimg.pl",
    "placeholderimage",
]

_IMAGE_PLACEHOLDER_FILENAMES = [
    r"image\d+\.\w+",
    r"photo\d+\.\w+",
    r"img[_-]?\d+",
    r"default\.\w+",
    r"sample\.\w+",
    r"placeholder",
    r"no[_-]?image",
    r"blank\.\w+",
    r"dummy",
]

_URL_PLACEHOLDER_PATTERNS = [
    "example.com",
    "javascript:void",
    "javascript:;",
]

_EMAIL_PLACEHOLDER_PATTERNS = [
    r"info@example\.com",
    r"name@example\.com",
    r"email@domain\.com",
    r"user@example\.",
    r"test@test\.",
    r"your@email\.",
    r"name@domain\.",
]


class PlaceholderDetector:
    """
    Evaluates whether field content is placeholder or real.

    Layer 1: Deterministic pattern matching (runs first, no LLM cost).
    Layer 2: LLM-assisted (only if Layer 1 inconclusive).
    Images: Layer 1 only, no vision model — inconclusive → NEEDS_USER_CONFIRMATION.
    """

    def __init__(self, llm_guard: LLMGuard):
        self.llm_guard = llm_guard

    def evaluate_field(
        self, value: Optional[str], field_type: FormFieldType
    ) -> PlaceholderResult:
        """
        Evaluate whether content is placeholder or real.

        Returns PlaceholderResult with appropriate ContentState.
        """
        # Handle None/empty values
        if value is None or value.strip() == "":
            return PlaceholderResult(
                is_placeholder=True,
                confidence=0.95,
                content_state=ContentState.CONFIRMED_PLACEHOLDER,
                signals=["empty_value"],
                replacement_slot_type=field_type.value,
            )

        value = value.strip()

        # Layer 1: deterministic
        layer1_result = self._layer1_deterministic(value, field_type)
        if layer1_result is not None:
            return layer1_result

        # For IMAGE type, don't attempt LLM — default to NEEDS_USER_CONFIRMATION
        if field_type == FormFieldType.IMAGE:
            return PlaceholderResult(
                is_placeholder=False,
                confidence=0.50,
                content_state=ContentState.NEEDS_USER_CONFIRMATION,
                signals=["image_inconclusive_no_vision_model"],
            )

        # Layer 2: LLM-assisted
        return self._layer2_llm_assisted(value, field_type)

    def _layer1_deterministic(
        self, value: str, field_type: FormFieldType
    ) -> Optional[PlaceholderResult]:
        """
        Deterministic pattern matching. Returns None if inconclusive.
        """
        value_lower = value.lower()

        # TEXT / TEXTAREA patterns
        if field_type in (FormFieldType.TEXT, FormFieldType.TEXTAREA):
            for pattern in _TEXT_PLACEHOLDER_PATTERNS:
                if re.search(pattern, value_lower):
                    return PlaceholderResult(
                        is_placeholder=True,
                        confidence=0.95,
                        content_state=ContentState.CONFIRMED_PLACEHOLDER,
                        signals=[f"text_pattern:{pattern}"],
                        replacement_slot_type=field_type.value,
                    )

            # Check email patterns in text fields
            for pattern in _EMAIL_PLACEHOLDER_PATTERNS:
                if re.search(pattern, value_lower):
                    return PlaceholderResult(
                        is_placeholder=True,
                        confidence=0.90,
                        content_state=ContentState.CONFIRMED_PLACEHOLDER,
                        signals=[f"email_pattern:{pattern}"],
                        replacement_slot_type=field_type.value,
                    )

            # Suspiciously short text
            if len(value) <= 2:
                return PlaceholderResult(
                    is_placeholder=True,
                    confidence=0.70,
                    content_state=(
                        ContentState.CONFIRMED_PLACEHOLDER
                        if 0.70 >= PLACEHOLDER_CONFIDENCE_THRESHOLD
                        else ContentState.NEEDS_USER_CONFIRMATION
                    ),
                    signals=["suspiciously_short_text"],
                    replacement_slot_type=field_type.value,
                )

            # Real content signal: substantial text with no placeholder patterns
            if len(value) > 20:
                return PlaceholderResult(
                    is_placeholder=False,
                    confidence=0.80,
                    content_state=ContentState.CONFIRMED_REAL,
                    signals=["substantial_text_no_patterns"],
                )

        # IMAGE patterns
        if field_type == FormFieldType.IMAGE:
            # Check placeholder image hosts
            for host in _IMAGE_PLACEHOLDER_HOSTS:
                if host in value_lower:
                    return PlaceholderResult(
                        is_placeholder=True,
                        confidence=0.95,
                        content_state=ContentState.CONFIRMED_PLACEHOLDER,
                        signals=[f"placeholder_image_host:{host}"],
                        replacement_slot_type="image",
                    )

            # Check placeholder image filenames
            for pattern in _IMAGE_PLACEHOLDER_FILENAMES:
                if re.search(pattern, value_lower):
                    return PlaceholderResult(
                        is_placeholder=True,
                        confidence=0.85,
                        content_state=ContentState.CONFIRMED_PLACEHOLDER,
                        signals=[f"placeholder_image_filename:{pattern}"],
                        replacement_slot_type="image",
                    )

        # URL patterns
        if field_type == FormFieldType.URL:
            for pattern in _URL_PLACEHOLDER_PATTERNS:
                if pattern in value_lower:
                    return PlaceholderResult(
                        is_placeholder=True,
                        confidence=0.90,
                        content_state=ContentState.CONFIRMED_PLACEHOLDER,
                        signals=[f"url_pattern:{pattern}"],
                        replacement_slot_type="url",
                    )

            # Single '#' hash links
            if value.strip() == "#":
                return PlaceholderResult(
                    is_placeholder=True,
                    confidence=0.90,
                    content_state=ContentState.CONFIRMED_PLACEHOLDER,
                    signals=["hash_only_url"],
                    replacement_slot_type="url",
                )

        # COLOR patterns — hex colors are rarely "placeholder"
        if field_type == FormFieldType.COLOR:
            return PlaceholderResult(
                is_placeholder=False,
                confidence=0.80,
                content_state=ContentState.CONFIRMED_REAL,
                signals=["color_value_assumed_real"],
            )

        return None  # Inconclusive

    def _layer2_llm_assisted(
        self, value: str, field_type: FormFieldType
    ) -> PlaceholderResult:
        """
        LLM-assisted evaluation (only called if Layer 1 inconclusive).

        Uses llm_guard.call_placeholder() for live LLM calls when a
        client is wired. Falls back to NEEDS_USER_CONFIRMATION when
        no client is available or the call fails (fail-closed).
        """
        # Attempt live LLM placeholder detection
        llm_result = self.llm_guard.call_placeholder(value, field_type.value)
        if llm_result is not None:
            logger.info(
                "placeholder_llm_resolved",
                field_type=field_type.value,
                is_placeholder=llm_result.is_placeholder,
                confidence=llm_result.confidence,
            )
            return llm_result

        # LLM unavailable or failed — fail closed to NEEDS_USER_CONFIRMATION
        logger.info("placeholder_llm_unavailable", field_type=field_type.value)
        return PlaceholderResult(
            is_placeholder=False,
            confidence=0.50,
            content_state=ContentState.NEEDS_USER_CONFIRMATION,
            signals=["llm_unavailable_or_failed"],
        )

    def evaluate_siblings_for_duplicates(self, values: List[str]) -> bool:
        """
        Check if >= 2 values are identical (indicating template content).
        """
        if len(values) < 2:
            return False

        cleaned = [v.strip().lower() for v in values if v and v.strip()]
        if len(cleaned) < 2:
            return False

        from collections import Counter

        counts = Counter(cleaned)
        has_duplicates = any(c >= 2 for c in counts.values())

        if has_duplicates:
            logger.info("placeholder_duplicates_detected", count=len(cleaned))

        return has_duplicates
