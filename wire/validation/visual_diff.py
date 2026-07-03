import hashlib
import os

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
        Lightweight perceptual hash. Computes an average-brightness
        fingerprint over 8x8 grid cells of raw pixel data.
        For production, swap in pHash / dHash with Pillow or imagehash.
        """
        # Simple byte-level fingerprint (works without Pillow)
        block_size = max(1, len(image_bytes) // 64)
        bits = []
        total = 0
        values = []
        for i in range(64):
            start = i * block_size
            end = start + block_size
            block = image_bytes[start:end]
            val = sum(block) / max(len(block), 1)
            values.append(val)
            total += val

        avg = total / 64
        for val in values:
            bits.append("1" if val >= avg else "0")

        return hex(int("".join(bits), 2))

    @staticmethod
    def hamming_distance(hash_a: str, hash_b: str) -> int:
        """Hamming distance between two hex-encoded perceptual hashes."""
        int_a = int(hash_a, 16)
        int_b = int(hash_b, 16)
        xor = int_a ^ int_b
        return bin(xor).count("1")

    def compare_pixel_fidelity(
        self,
        original_path: str,
        reconstruction_path: str,
        color_tolerance: int = 15,
    ) -> dict:
        """
        Compare two images pixel-by-pixel using decoded RGB values from Pillow.

        Args:
            original_path: Path to the original screenshot PNG.
            reconstruction_path: Path to the reconstructed screenshot PNG.
            color_tolerance: Maximum absolute difference per channel (R, G, B)
                for a pixel to be counted as matching. Default is 15.

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

        total_pixels = matching_pixels.size
        matched_pixels_count = np.sum(matching_pixels)
        similarity = float((matched_pixels_count / total_pixels) * 100.0)

        mae = float(np.mean(diff))
        mse = float(np.mean(diff**2))

        return {
            "similarity_percent": round(similarity, 2),
            "total_pixels": int(total_pixels),
            "matched_pixels": int(matched_pixels_count),
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
    ) -> dict:
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
            original_path, reconstruction_path, color_tolerance=color_tolerance
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
    ) -> dict:
        """
        Like compare_screenshots, but tolerant of dimension mismatches.

        Full-page screenshots of a live original vs. a static local reconstruction
        commonly differ in total height (dynamic content, fonts loading, ads, etc.).
        compare_screenshots/compare_pixel_fidelity intentionally raise on mismatch
        for callers that require strict equality; this variant resizes the
        reconstruction to the original's dimensions first so a similarity score
        can still be produced, flagging that a resize occurred.
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

        normalized_path = reconstruction_path
        resized = False
        with Image.open(reconstruction_path) as img_recon:
            if img_recon.convert("RGB").size != target_size:
                resized = True
                normalized_path = f"{reconstruction_path}.normalized.png"
                img_recon.convert("RGB").resize(target_size, Image.LANCZOS).save(
                    normalized_path
                )

        try:
            result = self.compare_screenshots(
                original_path, normalized_path, color_tolerance=color_tolerance
            )
        finally:
            if resized and os.path.exists(normalized_path):
                try:
                    os.remove(normalized_path)
                except OSError:
                    pass

        result["dimension_normalized"] = resized
        return result
