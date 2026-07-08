"""Per-breakpoint visual validation: SSIM at 768/480 caps the fidelity score."""

from wire.agents.observation.computed_style_capturer import ComputedStyleCapturer
from wire.agents.observation.viewport_renderer import ViewportRenderer
from wire.utils.fidelity_scorer import FidelityScorer


def test_validated_viewports_match_responsive_breakpoints():
    # The widths we screenshot the original at must include exactly the
    # breakpoints the computed-style capture claims to reproduce (768/480),
    # or the validation would be measuring something else.
    widths = {v["width"] for v in ViewportRenderer.VIEWPORTS.values()}
    breakpoint_widths = {w for _, w in ComputedStyleCapturer.DEFAULT_BREAKPOINTS}
    assert breakpoint_widths <= widths
    assert ViewportRenderer.VIEWPORTS["tablet"]["width"] == 768
    assert ViewportRenderer.VIEWPORTS["mobile_small"]["width"] == 480


def test_mean_of_breakpoint_scores_caps_fidelity():
    scorer = FidelityScorer()
    scorer.record_visual_similarity(95.0)
    scorer.record_structural_similarity(98.0)
    # Desktop looks fine, but the mobile rendering diverges.
    scorer.record_responsive_visual_similarity({"tablet": 90.0, "mobile_small": 60.0})
    assert scorer.responsive_visual_similarity == 75.0
    assert scorer.responsive_visual_breakdown == {
        "tablet": 90.0,
        "mobile_small": 60.0,
    }
    # Cap is the breakpoint mean (75), below desktop visual (95).
    assert scorer.compute_score() == 75.0


def test_good_breakpoints_do_not_lower_score():
    scorer = FidelityScorer()
    scorer.record_visual_similarity(85.0)
    scorer.record_responsive_visual_similarity({"tablet": 99.0, "mobile_small": 97.0})
    assert scorer.compute_score() == 85.0  # desktop remains the binding cap


def test_low_breakpoint_score_is_not_a_critical_error():
    # Desktop catches catastrophic divergence; a weak mobile layout lowers the
    # score but must not zero the run.
    scorer = FidelityScorer()
    scorer.record_responsive_visual_similarity({"mobile_small": 20.0})
    assert scorer.critical_errors == 0
    assert scorer.compute_score() == 20.0


def test_empty_or_none_breakpoint_scores_are_ignored():
    scorer = FidelityScorer()
    scorer.record_responsive_visual_similarity({})
    assert scorer.responsive_visual_similarity is None
    scorer.record_responsive_visual_similarity({"tablet": None})  # type: ignore[dict-item]
    assert scorer.responsive_visual_similarity is None
    assert scorer.compute_score() == 100.0  # no measurement -> no cap


def test_unmeasured_runs_are_unaffected():
    # Offline/browserless runs never record breakpoint scores; behavior is
    # identical to before the feature existed.
    scorer = FidelityScorer()
    scorer.record_visual_similarity(80.0)
    assert scorer.compute_score() == 80.0
