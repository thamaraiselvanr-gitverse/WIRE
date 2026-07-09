"""Branch coverage for InputBlueprint.validate_input (hard/soft/valid paths)."""

from wire.schema.input_blueprint import DataSlot, InputBlueprint, SlotConstraint


def _bp(**slots):
    return InputBlueprint(slots=slots)


def _slot(sid, stype, **cons):
    return DataSlot(
        id=sid, type=stype, constraint=SlotConstraint(allowed_types=[stype], **cons)
    )


def test_missing_slot_is_invalid():
    bp = _bp()
    res = bp.validate_input("nope", "x")
    assert res["valid"] is False


def test_text_length_and_placeholder_soft_warnings():
    bp = _bp(slot_t=_slot("slot_t", "text", max_length=5))
    over = bp.validate_input("slot_t", "way too long")
    assert over["valid"] is True and over["severity"] == "soft"

    bp2 = _bp(slot_t=_slot("slot_t", "text"))
    lorem = bp2.validate_input("slot_t", "Lorem ipsum dolor")
    assert lorem["severity"] == "soft"


def test_image_placeholder_and_dimensions_soft():
    bp = _bp(slot_i=_slot("slot_i", "image", max_width=100))
    ph = bp.validate_input("slot_i", "assets/placeholder-hero.png")
    assert ph["severity"] == "soft"

    big = bp.validate_input("slot_i", {"width": 500, "height": 10})
    assert big["severity"] == "soft"


def test_media_type_mismatch_is_hard():
    bp = _bp(slot_v=_slot("slot_v", "video"))
    res = bp.validate_input("slot_v", {"not": "a string"})
    assert res["valid"] is False and res["severity"] == "hard"
