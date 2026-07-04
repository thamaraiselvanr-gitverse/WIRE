"""Fail-closed validation and input-prep branches of LLMGuard (no live LLM)."""

from wire.schema.canonical import ComponentNode
from wire.schema.semantic_schema import ContentState, SectionRole
from wire.semantic.llm_guard import LLMGuard

_ROLE = next(iter(SectionRole)).value  # any valid role string


def _guard(**kw):
    return LLMGuard(**kw)


# ── budget ──
def test_budget_exhaustion_blocks_prep():
    g = _guard(max_calls_per_run=1)
    assert g.prepare_intent_input("do things") is not None  # 1st call ok
    assert g.prepare_intent_input("more") is None  # budget spent
    g.reset_call_count()
    assert g.prepare_intent_input("again") is not None


# ── classification ──
def test_validate_classification_rejects_bad_shapes():
    g = _guard()
    assert g.validate_classification("not a dict") is None
    assert g.validate_classification({"confidence": 0.9}) is None  # missing role
    assert (
        g.validate_classification(
            {"section_role": "nonsense_role", "confidence": 0.9, "reasoning": "x"}
        )
        is None
    )
    assert (
        g.validate_classification(
            {"section_role": _ROLE, "confidence": "high", "reasoning": "x"}
        )
        is None
    )  # confidence not numeric
    assert (
        g.validate_classification(
            {"section_role": _ROLE, "confidence": 1.5, "reasoning": "x"}
        )
        is None
    )  # out of range
    assert (
        g.validate_classification(
            {"section_role": _ROLE, "confidence": 0.01, "reasoning": "x"}
        )
        is None
    )  # below threshold
    assert (
        g.validate_classification(
            {"section_role": _ROLE, "confidence": 0.99, "reasoning": "   "}
        )
        is None
    )  # empty reasoning


def test_validate_classification_accepts_valid():
    g = _guard()
    result = g.validate_classification(
        {"section_role": _ROLE, "confidence": 0.99, "reasoning": "clear nav"}
    )
    assert result is not None
    assert result.section_role.value == _ROLE
    assert result.is_heuristic is False


# ── placeholder ──
def test_validate_placeholder_branches():
    g = _guard()
    assert g.validate_placeholder("nope") is None
    assert (
        g.validate_placeholder({"is_likely_placeholder": "yes", "confidence": 0.9})
        is None
    )
    assert (
        g.validate_placeholder({"is_likely_placeholder": True, "confidence": "x"})
        is None
    )
    assert (
        g.validate_placeholder({"is_likely_placeholder": True, "confidence": 2}) is None
    )

    confirmed_ph = g.validate_placeholder(
        {"is_likely_placeholder": True, "confidence": 0.99}
    )
    assert confirmed_ph.content_state == ContentState.CONFIRMED_PLACEHOLDER

    confirmed_real = g.validate_placeholder(
        {"is_likely_placeholder": False, "confidence": 0.99}
    )
    assert confirmed_real.content_state == ContentState.CONFIRMED_REAL

    needs = g.validate_placeholder({"is_likely_placeholder": True, "confidence": 0.05})
    assert needs.content_state == ContentState.NEEDS_USER_CONFIRMATION


# ── intent ──
def test_validate_intent_extraction_branches():
    g = _guard()
    assert g.validate_intent_extraction("nope") is None
    assert g.validate_intent_extraction({"unrelated": 1}) is None  # no canonical keys
    assert g.validate_intent_extraction({"sections_to_exclude": "notalist"}) is None
    assert (
        g.validate_intent_extraction({"sections_to_emphasize": ["not_a_real_role"]})
        is None
    )
    valid = g.validate_intent_extraction(
        {"user_role_domain": "law", "sections_to_emphasize": [_ROLE]}
    )
    assert isinstance(valid, dict)


# ── input prep ──
def test_prepare_placeholder_input_size_and_budget():
    g = _guard(max_input_chars=10)
    assert g.prepare_placeholder_input("short", "text") == {
        "value": "short",
        "field_type": "text",
    }
    assert g.prepare_placeholder_input("x" * 50, "text") is None  # too large


def test_prepare_classification_input_size_and_budget():
    small = ComponentNode(tag="p", text_content="hi")
    assert _guard(max_input_chars=100).prepare_classification_input(small) is not None

    big = ComponentNode(tag="div", text_content="y" * 200)
    assert _guard(max_input_chars=50).prepare_classification_input(big) is None

    starved = _guard(max_calls_per_run=0)
    assert starved.prepare_classification_input(small) is None  # no budget
