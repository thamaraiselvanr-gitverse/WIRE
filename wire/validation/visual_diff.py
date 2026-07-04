import hashlib
import os
from io import BytesIO
from typing import Any, Dict, List, Optional

import numpy as np
import structlog
from PIL import Image

logger = structlog.get_logger(__name__)


class VisualDiff:
    """
    Perceptual hashing and pixel-level diff between original and reconstruction.
    """

    @staticmethod
    def file_hash(filepath: str) -> str:
        """SHA-256 hash of a file for integrity checks."""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def perceptual_hash(image_bytes: bytes) -> str:
        """
        Real average-hash (aHash): decode the image, downscale to 8x8 grayscale,
        and threshold each pixel against the mean brightness to form a 64-bit
        perceptual fingerprint. Unlike a byte-level hash, small visual changes
        produce small Hamming distances, so hamming_distance() is meaningful.
        """
        try:
            img = Image.open(BytesIO(image_bytes)).convert("L").resize((8, 8))
            arr = np.asarray(img, dtype=np.float64)
            avg = float(arr.mean())
            bits = "".join("1" if p >= avg else "0" for p in arr.flatten())
            return hex(int(bits, 2))
        except Exception as e:
            logger.warning("perceptual_hash_failed", error=str(e))
            return hex(0)

    @staticmethod
    def hamming_distance(hash_a: str, hash_b: str) -> int:
        """Hamming distance between two hex-encoded perceptual hashes."""
        int_a = int(hash_a, 16)
        int_b = int(hash_b, 16)
        xor = int_a ^ int_b
        return bin(xor).count("1")

    @staticmethod
    def volatility_mask(
        image_paths: List[Any], color_tolerance: int = 15
    ) -> Optional[np.ndarray]:
        """Detect dynamic (non-deterministic) regions across repeated renders of
        the same page.

        Given multiple same-size screenshots of one page, returns a boolean mask
        (True = volatile) marking pixels whose value varies across the renders by
        more than ``color_tolerance`` — i.e. ads, carousels, videos, animations.
        Feeding this mask to the visual comparison stops such regions from
        penalizing the reconstruction fidelity score. Returns None if fewer than
        two images are given or their dimensions differ.
        """
        existing = [p for p in image_paths if p and os.path.exists(p)]
        if len(existing) < 2:
            return None
        arrays = [
            np.array(Image.open(p).convert("RGB"), dtype=np.int32) for p in existing
        ]
        base_shape = arrays[0].shape
        if any(a.shape != base_shape for a in arrays):
            return None
        stack = np.stack(arrays, axis=0)
        spread = stack.max(axis=0) - stack.min(axis=0)
        return np.any(spread > color_tolerance, axis=-1)  # type: ignore[no-any-return]

    def compare_pixel_fidelity(
        self,
        original_path: str,
        reconstruction_path: str,
        color_tolerance: int = 15,
        ignore_mask: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Compare two images pixel-by-pixel using decoded RGB values from Pillow.

        Args:
            original_path: Path to the original screenshot PNG.
            reconstruction_path: Path to the reconstructed screenshot PNG.
            color_tolerance: Maximum absolute difference per channel (R, G, B)
                for a pixel to be counted as matching. Default is 15.
            ignore_mask: Optional boolean array (True = ignore) of dynamic
                regions to exclude from the similarity calculation.

        Returns:
            A dictionary containing comparison metrics.

        Raises:
            ValueError: If the images have mismatched dimensions.
        """
        if not os.path.exists(original_path):
            raise FileNotFoundError(f"Original image file not found: {original_path}")
        if not os.path.exists(reconstruction_path):
            raise FileNotFoundError(
                f"Reconstruction image file not found: {reconstruction_path}"
            )

        img_orig = Image.open(original_path).convert("RGB")
        img_recon = Image.open(reconstruction_path).convert("RGB")

        if img_orig.size != img_recon.size:
            raise ValueError(
                f"Image dimensions do not match: "
                f"original={img_orig.size} (w={img_orig.width}, h={img_orig.height}), "
                f"reconstruction={img_recon.size} (w={img_recon.width}, h={img_recon.height})"
            )

        arr_orig = np.array(img_orig, dtype=np.int32)
        arr_recon = np.array(img_recon, dtype=np.int32)

        # Calculate absolute difference per channel
        diff = np.abs(arr_orig - arr_recon)

        # A pixel matches if all channels are within color_tolerance
        matching_channels = diff <= color_tolerance
        matching_pixels = np.all(matching_channels, axis=-1)

        ignored_pixels = 0
        if ignore_mask is not None and ignore_mask.shape == matching_pixels.shape:
            considered = ~ignore_mask
            total_pixels = int(considered.sum())
            matched_pixels_count = int((matching_pixels & considered).sum())
            ignored_pixels = int(ignore_mask.sum())
            diff_considered = diff[considered]
            mae = float(np.mean(diff_considered)) if total_pixels else 0.0
            mse = float(np.mean(diff_considered**2)) if total_pixels else 0.0
        else:
            total_pixels = matching_pixels.size
            matched_pixels_count = int(np.sum(matching_pixels))
            mae = float(np.mean(diff))
            mse = float(np.mean(diff**2))

        similarity = (
            float((matched_pixels_count / total_pixels) * 100.0)
            if total_pixels
            else 100.0
        )

        return {
            "similarity_percent": round(similarity, 2),
            "total_pixels": int(total_pixels),
            "matched_pixels": int(matched_pixels_count),
            "ignored_pixels": ignored_pixels,
            "mae": round(mae, 4),
            "mse": round(mse, 4),
            "comparison_method": "pixel-based (color delta)",
            "tolerance": color_tolerance,
        }

    def compare_screenshots(
        self,
        original_path: str,
        reconstruction_path: str,
        color_tolerance: int = 15,
        ignore_mask: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Compare two screenshot files and return a fidelity report.
        Uses compare_pixel_fidelity for the final similarity percentage.
        """
        logger.info(
            "comparing_visual_fidelity",
            original=original_path,
            reconstruction=reconstruction_path,
        )

        if not os.path.exists(original_path) or not os.path.exists(reconstruction_path):
            return {
                "error": "One or both files missing",
                "similarity_percent": 0.0,
                "comparison_method": "pixel-based (color delta)",
                "tolerance": color_tolerance,
            }

        # 1. Retrieve pixel fidelity
        pixel_result = self.compare_pixel_fidelity(
            original_path,
            reconstruction_path,
            color_tolerance=color_tolerance,
            ignore_mask=ignore_mask,
        )

        # 2. Get byte-level perceptual hashes and file hashes (diagnostic only)
        with open(original_path, "rb") as f:
            orig_bytes = f.read()
        with open(reconstruction_path, "rb") as f:
            recon_bytes = f.read()

        orig_hash = self.perceptual_hash(orig_bytes)
        recon_hash = self.perceptual_hash(recon_bytes)
        distance = self.hamming_distance(orig_hash, recon_hash)

        # Merge results, ensuring similarity_percent is the pixel-based one
        result = {
            "original_sha256": self.file_hash(original_path),
            "reconstruction_sha256": self.file_hash(reconstruction_path),
            "original_phash": orig_hash,
            "reconstruction_phash": recon_hash,
            "hamming_distance": distance,
            **pixel_result,
        }

        logger.info("visual_diff_complete", similarity=result["similarity_percent"])
        return result

    def compare_screenshots_normalized(
        self,
        original_path: str,
        reconstruction_path: str,
        color_tolerance: int = 15,
        ignore_mask: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Like compare_screenshots, but tolerant of dimension mismatches.

        Full-page screenshots of a live original vs. a static local reconstruction
        commonly differ in total height (dynamic content, fonts loading, ads, etc.).
        compare_screenshots/compare_pixel_fidelity intentionally raise on mismatch
        for callers that require strict equality; this variant resizes the
        reconstruction to the original's dimensions first so a similarity score
        can still be produced, flagging that a resize occurred.

        ``ignore_mask`` (dynamic regions in the original) is applied only when it
        matches the original's dimensions.
        """
        if not os.path.exists(original_path) or not os.path.exists(reconstruction_path):
            return {
                "error": "One or both files missing",
                "similarity_percent": 0.0,
                "comparison_method": "pixel-based (color delta)",
                "tolerance": color_tolerance,
            }

        with Image.open(original_path) as img_orig:
            target_size = img_orig.convert("RGB").size

        # (w, h) size -> (h, w) mask shape; only apply if it lines up.
        safe_mask = None
        if ignore_mask is not None and ignore_mask.shape == (
            target_size[1],
            target_size[0],
        ):
            safe_mask = ignore_mask

        normalized_path = reconstruction_path
        resized = False
        with Image.open(reconstruction_path) as img_recon:
            if img_recon.convert("RGB").size != target_size:
                resized = True
                normalized_path = f"{reconstruction_path}.normalized.png"
                img_recon.convert("RGB").resize(
                    target_size, Image.Resampling.LANCZOS
                ).save(normalized_path)

        try:
            result = self.compare_screenshots(
                original_path,
                normalized_path,
                color_tolerance=color_tolerance,
                ignore_mask=safe_mask,
            )
        finally:
            if resized and os.path.exists(normalized_path):
                try:
                    os.remove(normalized_path)
                except OSError:
                    pass

        result["dimension_normalized"] = resized
        return result
