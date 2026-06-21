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
