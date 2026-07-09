"""SSIM perceptual metric and its exposure through compare_screenshots."""

import numpy as np
from PIL import Image

from wire.validation.visual_diff import VisualDiff


def _solid(size, color):
    return Image.new("RGB", size, color)


def test_ssim_identical_is_full():
    img = _solid((120, 90), (128, 64, 200))
    assert VisualDiff.compute_ssim(img, img) == 100.0


def test_ssim_black_vs_white_is_near_zero():
    black = _solid((120, 90), (0, 0, 0))
    white = _solid((120, 90), (255, 255, 255))
    assert VisualDiff.compute_ssim(black, white) < 20.0


def test_ssim_tolerates_dimension_mismatch():
    a = _solid((200, 200), (50, 50, 50))
    b = _solid((100, 60), (50, 50, 50))
    # Same content, different size -> resized internally, still high similarity.
    assert VisualDiff.compute_ssim(a, b) > 90.0


def test_ssim_ignore_mask_excludes_volatile_region():
    # Top half of B differs (a "volatile" banner); bottom half identical to A.
    a = np.full((100, 100, 3), 128, dtype=np.uint8)
    b = a.copy()
    b[0:50, :, :] = 255
    img_a = Image.fromarray(a)
    img_b = Image.fromarray(b)

    without = VisualDiff.compute_ssim(img_a, img_b)
    mask = np.zeros((100, 100), dtype=bool)
    mask[0:50, :] = True  # mark the differing region volatile
    with_mask = VisualDiff.compute_ssim(img_a, img_b, ignore_mask=mask)

    assert with_mask > without
    assert with_mask > 85.0


def test_compare_screenshots_exposes_ssim(tmp_path):
    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    _solid((80, 80), (10, 120, 30)).save(p1)
    _solid((80, 80), (10, 120, 30)).save(p2)
    result = VisualDiff().compare_screenshots(str(p1), str(p2))
    assert "ssim_percent" in result
    assert result["ssim_percent"] == 100.0
    # Pixel metric is still present for backward compatibility.
    assert "similarity_percent" in result
