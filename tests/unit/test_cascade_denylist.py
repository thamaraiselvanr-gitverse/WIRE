"""CascadeResolver keeps non-core visual props (denylist) but drops behavioral ones."""

from wire.schema.style_mapper import CascadeResolver


def test_denylist_keeps_noncore_visual_and_drops_behavioral():
    resolver = CascadeResolver()
    html = "<html><body><div class='x'>hi</div></body></html>"
    css = ".x { color: blue; caret-color: red; pointer-events: none; }"
    soup, styles = resolver.resolve(html, css)
    div = soup.select_one(".x")
    resolved = styles[id(div)]

    assert resolved.get("color") == "blue"
    # caret-color is not in the core reference set but is a real paint property;
    # the denylist gate keeps it instead of silently dropping it.
    assert resolved.get("caret-color") == "red"
    # pointer-events is non-visual/behavioral -> denied.
    assert "pointer-events" not in resolved


def test_accept_prop_gate():
    resolver = CascadeResolver()
    assert resolver._accept_prop("clip-path")
    assert resolver._accept_prop("--brand-color")  # custom props always kept
    assert resolver._accept_prop("some-future-paint-prop")
    assert not resolver._accept_prop("will-change")
    assert not resolver._accept_prop("content")
