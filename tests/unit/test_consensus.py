import pytest
from io import BytesIO
from PIL import Image
from wire.orchestrator.consensus import ConsensusValidator


def make_mock_png(color, size=(10, 10)):
    img = Image.new("RGB", size, color=color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_consensus_validator_perfect():
    validator = ConsensusValidator(quorum_size=3, threshold=95.0)

    # 3 identical red renders
    render = make_mock_png((255, 0, 0))
    renders = [render, render, render]

    res = await validator.validate(renders)
    assert res["consensus"] is True
    assert res["agreement"] == 100.0
    assert len(res["pair_details"]) == 3


@pytest.mark.asyncio
async def test_consensus_validator_partial_agreement():
    validator = ConsensusValidator(quorum_size=3, threshold=95.0)

    # 2 identical red renders, 1 green render
    # Pairwise:
    # 0 vs 1 (red vs red) -> 100%
    # 1 vs 2 (red vs green) -> 0%
    # 0 vs 2 (red vs green) -> 0%
    # Average agreement: (100 + 0 + 0) / 3 = 33.33%
    r_red = make_mock_png((255, 0, 0))
    r_green = make_mock_png((0, 255, 0))
    renders = [r_red, r_red, r_green]

    res = await validator.validate(renders)
    assert res["consensus"] is False
    assert res["agreement"] == 33.33


@pytest.mark.asyncio
async def test_consensus_validator_dimension_mismatch():
    validator = ConsensusValidator(quorum_size=3, threshold=50.0)

    # Render 0: red 10x10
    # Render 1: red 10x10
    # Render 2: red 12x10 (dimension mismatch)
    # Pairwise:
    # 0 vs 1 (10x10 vs 10x10) -> 100%
    # 1 vs 2 (10x10 vs 12x10) -> ValueError caught, 0%
    # 0 vs 2 (10x10 vs 12x10) -> ValueError caught, 0%
    # Average agreement: (100 + 0 + 0) / 3 = 33.33%
    r1 = make_mock_png((255, 0, 0), size=(10, 10))
    r2 = make_mock_png((255, 0, 0), size=(12, 10))
    renders = [r1, r1, r2]

    res = await validator.validate(renders)
    assert res["consensus"] is False
    assert res["agreement"] == 33.33
