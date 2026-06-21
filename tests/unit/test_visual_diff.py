import os
import tempfile
import pytest
from PIL import Image
from wire.validation.visual_diff import VisualDiff


def test_visual_diff_sanity_check():
    # Create two temporary images of the same dimensions but different content
    with tempfile.TemporaryDirectory() as tmpdir:
        img_path1 = os.path.join(tmpdir, "img1.png")
        img_path2 = os.path.join(tmpdir, "img2.png")
        img_path3 = os.path.join(tmpdir, "img3.png")  # Mismatched dimension

        # Image 1: solid red 10x10
        img1 = Image.new("RGB", (10, 10), color=(255, 0, 0))
        img1.save(img_path1)

        # Image 2: mostly red, but 10 pixels are blue
        img2 = Image.new("RGB", (10, 10), color=(255, 0, 0))
        for i in range(10):
            img2.putpixel((i, i), (0, 0, 255))
        img2.save(img_path2)

        # Image 3: solid red 12x10 (different dimensions)
        img3 = Image.new("RGB", (12, 10), color=(255, 0, 0))
        img3.save(img_path3)

        diff = VisualDiff()

        # 1. Compare identical images: should be 100%
        res_ident = diff.compare_screenshots(img_path1, img_path1)
        assert res_ident["similarity_percent"] == 100.0
        assert res_ident["comparison_method"] == "pixel-based (color delta)"
        assert res_ident["mae"] == 0.0

        # 2. Compare known different images: should be exactly 90.0% similarity (10/100 mismatch)
        res_diff = diff.compare_screenshots(img_path1, img_path2, color_tolerance=15)
        assert res_diff["similarity_percent"] == 90.0
        assert res_diff["matched_pixels"] == 90
        assert res_diff["total_pixels"] == 100
        assert res_diff["mae"] > 0.0
        assert res_diff["mse"] > 0.0

        # 3. Mismatched dimensions: should raise ValueError
        with pytest.raises(ValueError) as excinfo:
            diff.compare_screenshots(img_path1, img_path3)
        assert "dimensions do not match" in str(excinfo.value)
