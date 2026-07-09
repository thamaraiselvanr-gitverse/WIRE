from wire.utils.fidelity_scorer import FidelityScorer


def test_fidelity_scorer_perfect():
    scorer = FidelityScorer()
    assert scorer.compute_score() == 100.0


def test_fidelity_scorer_non_critical():
    scorer = FidelityScorer()
    scorer.log_non_critical_error("test exception")
    assert scorer.compute_score() == 97.5


def test_fidelity_scorer_critical():
    scorer = FidelityScorer()
    scorer.log_non_critical_error("test exception")
    scorer.log_critical_error("fatal dom extraction failed")
    assert scorer.compute_score() == 0.0


def test_fidelity_scorer_visual_similarity_caps_score():
    # An error-free run whose reconstruction only visually matches 62% of the
    # original must not report 100% fidelity.
    scorer = FidelityScorer()
    scorer.record_visual_similarity(62.0)
    assert scorer.compute_score() == 62.0


def test_fidelity_scorer_structural_similarity_caps_score():
    scorer = FidelityScorer()
    scorer.record_structural_similarity(55.0)
    assert scorer.compute_score() == 55.0


def test_fidelity_scorer_visual_similarity_below_critical_threshold_zeroes_score():
    scorer = FidelityScorer()
    scorer.record_visual_similarity(10.0)
    assert scorer.critical_errors == 1
    assert scorer.compute_score() == 0.0


def test_fidelity_scorer_structural_similarity_below_critical_threshold_zeroes_score():
    scorer = FidelityScorer()
    scorer.record_structural_similarity(5.0)
    assert scorer.critical_errors == 1
    assert scorer.compute_score() == 0.0


def test_fidelity_scorer_high_similarity_does_not_lower_score():
    scorer = FidelityScorer()
    scorer.record_visual_similarity(99.5)
    scorer.record_structural_similarity(98.0)
    assert scorer.compute_score() == 98.0
