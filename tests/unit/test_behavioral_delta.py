from wire.agents.extraction.behavioral_extractor import BehavioralExtractor

delta = BehavioralExtractor._delta


def test_delta_reports_only_changed_props():
    base = {"color": "rgb(0, 0, 0)", "opacity": "1", "transform": "none"}
    after = {"color": "rgb(255, 0, 0)", "opacity": "1", "transform": "scale(1.1)"}
    d = delta(base, after)
    assert d == {
        "color": {"from": "rgb(0, 0, 0)", "to": "rgb(255, 0, 0)"},
        "transform": {"from": "none", "to": "scale(1.1)"},
    }


def test_delta_empty_when_unchanged():
    base = {"color": "rgb(0, 0, 0)"}
    assert delta(base, dict(base)) == {}


def test_delta_ignores_keys_missing_from_after():
    assert delta({"color": "a", "opacity": "1"}, {"color": "a"}) == {}
