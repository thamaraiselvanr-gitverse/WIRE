import base64
import io
import os
import uuid
from typing import Any, Dict

import structlog
from PIL import Image

logger = structlog.get_logger(__name__)


class ImageIngestionPipeline:
    """
    Ingests and sanitizes user-uploaded base64 images.
    Enforces sizes, verifies magic bytes, strips EXIF, and re-encodes.
    """

    @staticmethod
    def decode_and_verify(
        b64_string: str, max_size_bytes: int = 5 * 1024 * 1024  # 5MB default
    ) -> bytes:
        # Strip data URL prefix if present
        if "," in b64_string:
            b64_string = b64_string.split(",", 1)[1]

        try:
            decoded_bytes = base64.b64decode(b64_string)
        except Exception as e:
            raise ValueError(f"Base64 decoding failed: {str(e)}")

        # Enforce size limit
        if len(decoded_bytes) > max_size_bytes:
            raise ValueError(
                f"Image size ({len(decoded_bytes)} bytes) exceeds the limit of {max_size_bytes} bytes."
            )

        # Verify magic bytes
        ImageIngestionPipeline._verify_magic_bytes(decoded_bytes)
        return decoded_bytes

    @staticmethod
    def process(
        b64_string: str, target_dir: str, max_size_bytes: int = 5 * 1024 * 1024
    ) -> Dict[str, Any]:
        """
        Processes image from base64 string, saves to target_dir/user_uploads/,
        and returns details of the sanitized image.
        """
        decoded_bytes = ImageIngestionPipeline.decode_and_verify(
            b64_string, max_size_bytes
        )

        # Load through Pillow
        try:
            img = Image.open(io.BytesIO(decoded_bytes))
            # Force load image data to ensure it's not a lazy format logic bypass
            img.load()
        except Exception as e:
            raise ValueError(f"Failed to open image via Pillow: {str(e)}")

        img_format = img.format
        if not img_format:
            raise ValueError("Could not determine image format via Pillow.")

        # Re-save through Pillow to strip EXIF and re-encode
        # Limit dimensions to 2048x2048 to prevent memory/performance issues downstream
        if img.width > 2048 or img.height > 2048:
            img.thumbnail((2048, 2048))

        # Generate a unique, safe filename
        ext = img_format.lower()
        if ext == "jpeg":
            ext = "jpg"
        unique_name = f"{uuid.uuid4().hex}.{ext}"

        uploads_dir = os.path.join(target_dir, "user_uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        stored_path = os.path.join(uploads_dir, unique_name)

        # Re-encode to clean bytes (this strips EXIF/metadata natively as Pillow doesn't copy it unless requested)
        output_buffer = io.BytesIO()
        try:
            img.save(output_buffer, format=img_format)
            sanitized_bytes = output_buffer.getvalue()
        except Exception as e:
            raise ValueError(f"Failed to re-encode and save image: {str(e)}")

        # Save to disk
        with open(stored_path, "wb") as f:
            f.write(sanitized_bytes)

        # Make reference path relative to the run directory (e.g. assets/user_uploads/...)
        # Since target_dir is LocalStorage.get_asset_path() which is <run_dir>/assets,
        # we can form the relative path relative to target_dir's parent (the run_dir)
        run_dir = os.path.dirname(target_dir)
        relative_reference = os.path.relpath(stored_path, run_dir).replace("\\", "/")

        logger.info(
            "image_ingested_and_sanitized",
            original_size=len(decoded_bytes),
            sanitized_size=len(sanitized_bytes),
            dimensions=f"{img.width}x{img.height}",
            path=relative_reference,
        )

        return {
            "stored_path": relative_reference,
            "width": img.width,
            "height": img.height,
            "file_size": len(sanitized_bytes),
            "content_type": f"image/{ext}",
        }

    @staticmethod
    def _verify_magic_bytes(data: bytes) -> None:
        if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
            return  # PNG
        if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
            return  # JPEG
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return  # WebP
        raise ValueError(
            "Magic-byte verification failed: Unsupported or invalid image format."
        )
