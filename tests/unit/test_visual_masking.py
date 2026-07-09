import os
import tempfile

from PIL import Image

from wire.validation.visual_diff import VisualDiff


def _save(img: Image.Image, path: str) -> str:
    img.save(path)
    return path


def test_perceptual_hash_is_real_ahash():
    diff = VisualDiff()
    import io

    def to_bytes(img):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    # Base pattern: left half black, right half white.
    base = Image.new("L", (32, 32), color=0)
    for x in range(16, 32):
        for y in range(32):
            base.putpixel((x, y), 255)
    # Inverted pattern (opposite) -> maximally different aHash.
    inverted = Image.new("L", (32, 32), color=255)
    for x in range(16, 32):
        for y in range(32):
            inverted.putpixel((x, y), 0)
    # Near-identical: base with a single 4x4 block flipped.
    near = base.copy()
    for x in range(4):
        for y in range(4):
            near.putpixel((x, y), 255)

    h_base = diff.perceptual_hash(to_bytes(base))
    h_near = diff.perceptual_hash(to_bytes(near))
    h_inv = diff.perceptual_hash(to_bytes(inverted))

    assert diff.hamming_distance(h_base, h_base) == 0
    # A small change stays close; the inverse is far.
    assert diff.hamming_distance(h_base, h_near) < diff.hamming_distance(h_base, h_inv)


def test_volatility_mask_flags_changing_region():
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for i in range(3):
            img = Image.new("RGB", (10, 10), color=(0, 0, 0))
            # A single pixel changes across renders -> volatile.
            img.putpixel((5, 5), (i * 100, 0, 0))
            paths.append(_save(img, os.path.join(d, f"r{i}.png")))

        mask = VisualDiff.volatility_mask(paths)
        assert mask is not None
        assert mask[5, 5]  # (row, col) — volatile
        assert not mask[0, 0]  # stable


def test_volatility_mask_none_when_dims_differ():
    with tempfile.TemporaryDirectory() as d:
        p1 = _save(Image.new("RGB", (10, 10)), os.path.join(d, "a.png"))
        p2 = _save(Image.new("RGB", (12, 10)), os.path.join(d, "b.png"))
        assert VisualDiff.volatility_mask([p1, p2]) is None


def test_ignore_mask_excludes_volatile_region_from_score():
    with tempfile.TemporaryDirectory() as d:
        # Original all red; reconstruction identical except a 10-col band differs.
        orig = Image.new("RGB", (100, 10), color=(255, 0, 0))
        recon = Image.new("RGB", (100, 10), color=(255, 0, 0))
        for x in range(10):
            for y in range(10):
                recon.putpixel((x, y), (0, 0, 255))
        op = _save(orig, os.path.join(d, "orig.png"))
        rp = _save(recon, os.path.join(d, "recon.png"))

        diff = VisualDiff()
        # Without a mask: 100 of 1000 px differ -> 90%.
        unmasked = diff.compare_pixel_fidelity(op, rp)
        assert unmasked["similarity_percent"] == 90.0

        # Mask out the differing band (cols 0-9) -> the rest is a perfect match.
        mask = VisualDiff.volatility_mask([op, rp])  # marks the differing band
        masked = diff.compare_pixel_fidelity(op, rp, ignore_mask=mask)
        assert masked["similarity_percent"] == 100.0
        assert masked["ignored_pixels"] == 100
