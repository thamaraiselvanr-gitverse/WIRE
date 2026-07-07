"""Heuristic slot discovery — the no-LLM floor that makes pages repurposable."""

from wire.schema.canonical import ComponentNode
from wire.semantic.slot_discovery import HeuristicSlotDiscoverer


def _node(tag, text=None, attrs=None, children=None):
    node = ComponentNode(tag=tag, attributes=attrs or {}, children=children or [])
    if text is not None:
        node.children = [ComponentNode(tag="#text", text_content=text), *node.children]
    return node


def test_discovers_text_and_image_slots():
    root = _node(
        "body",
        children=[
            _node("h1", text="Acme Platform"),
            _node("p", text="Ship insights faster."),
            _node("img", attrs={"src": "logo.png"}),
            _node("a", text="Start free trial", attrs={"href": "/signup"}),
        ],
    )
    bp = HeuristicSlotDiscoverer().discover(root)

    assert len(bp.slots) == 4
    types = sorted(s.type for s in bp.slots.values())
    assert types == ["image", "text", "text", "text"]
    # slot_ids were bound onto the actual nodes (so substitution can target them).
    assert root.children[0].slot_id is not None
    assert root.children[2].slot_id is not None
    # Every blueprint slot id matches a node in the tree.
    assert set(HeuristicSlotDiscoverer.slot_ids(root)) == set(bp.slots)


def test_skips_whitespace_and_trivial_text():
    root = _node(
        "div",
        children=[
            _node("span", text="   "),  # whitespace only
            _node("span", text="•"),  # bullet / no alnum
            _node("span", text="Real content"),  # kept
            _node("div"),  # structural, no direct text
        ],
    )
    bp = HeuristicSlotDiscoverer().discover(root)
    assert len(bp.slots) == 1


def test_image_without_src_is_not_slotted():
    root = _node("div", children=[_node("img")])
    assert len(HeuristicSlotDiscoverer().discover(root).slots) == 0


def test_long_text_gets_generous_length_allowance():
    long_text = "word " * 60  # 300 chars -> should permit textarea downstream
    root = _node("p", text=long_text.strip())
    bp = HeuristicSlotDiscoverer().discover(root)
    slot = next(iter(bp.slots.values()))
    assert slot.constraint.max_length is not None
    assert slot.constraint.max_length > 200  # -> TEXTAREA in the form compiler


def test_slot_cap_is_enforced():
    disc = HeuristicSlotDiscoverer()
    root = ComponentNode(
        tag="body",
        children=[_node("p", text=f"item {i}") for i in range(disc.MAX_SLOTS + 50)],
    )
    bp = disc.discover(root)
    assert len(bp.slots) == disc.MAX_SLOTS


def test_discovery_is_idempotent_on_prebound_nodes():
    root = _node("h1", text="Title")
    disc = HeuristicSlotDiscoverer()
    bp1 = disc.discover(root)
    # Re-running does not re-slot already-bound nodes.
    bp2 = disc.discover(root)
    assert len(bp1.slots) == 1
    assert len(bp2.slots) == 0
