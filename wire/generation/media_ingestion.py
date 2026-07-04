import base64
import os
import uuid
from typing import Any, Dict, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


class MediaIngestionPipeline:
    """Ingests user-uploaded base64 video/audio.

    Verifies magic bytes against the declared media kind, enforces a size cap,
    stores the file under ``<target_dir>/user_uploads/`` with a random safe name,
    and returns the run-relative reference path plus metadata. Media is stored
    as-is (not re-encoded) — transcoding would require ffmpeg, which is out of
    scope; the magic-byte gate is the integrity control.
    """

    # 100MB default cap for A/V uploads.
    DEFAULT_MAX_BYTES = 100 * 1024 * 1024

    VIDEO_EXT = {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "ogv": "video/ogg",
        "mov": "video/quicktime",
    }
    AUDIO_EXT = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
    }

    @staticmethod
    def decode_and_verify(
        b64_string: str, kind: str, max_size_bytes: int = DEFAULT_MAX_BYTES
    ) -> Tuple[Any, ...]:
        """Decode base64, enforce size, verify magic bytes. Returns (bytes, ext)."""
        if "," in b64_string and b64_string.strip().startswith("data:"):
            b64_string = b64_string.split(",", 1)[1]
        try:
            data = base64.b64decode(b64_string)
        except Exception as e:
            raise ValueError(f"Base64 decoding failed: {e}")

        if len(data) > max_size_bytes:
            raise ValueError(
                f"Media size ({len(data)} bytes) exceeds the limit of "
                f"{max_size_bytes} bytes."
            )

        ext = MediaIngestionPipeline._detect_format(data, kind)
        if ext is None:
            raise ValueError(
                f"Magic-byte verification failed: not a recognized {kind} format."
            )
        return data, ext

    @classmethod
    def process(
        cls,
        b64_string: str,
        target_dir: str,
        kind: str,
        max_size_bytes: int = DEFAULT_MAX_BYTES,
    ) -> Dict[str, Any]:
        if kind not in ("video", "audio"):
            raise ValueError(f"Unsupported media kind: {kind}")

        data, ext = cls.decode_and_verify(b64_string, kind, max_size_bytes)

        uploads_dir = os.path.join(target_dir, "user_uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        stored_path = os.path.join(uploads_dir, unique_name)
        with open(stored_path, "wb") as f:
            f.write(data)

        run_dir = os.path.dirname(target_dir)
        relative_reference = os.path.relpath(stored_path, run_dir).replace("\\", "/")

        content_type = (cls.VIDEO_EXT if kind == "video" else cls.AUDIO_EXT).get(
            ext, f"{kind}/{ext}"
        )
        logger.info(
            "media_ingested",
            kind=kind,
            size=len(data),
            ext=ext,
            path=relative_reference,
        )
        return {
            "stored_path": relative_reference,
            "kind": kind,
            "file_size": len(data),
            "content_type": content_type,
        }

    @staticmethod
    def _detect_format(data: bytes, kind: str) -> Optional[str]:
        if kind == "video":
            if len(data) >= 12 and data[4:8] == b"ftyp":
                brand = data[8:12]
                return "mov" if brand[:3] == b"qt " else "mp4"
            if data[:4] == b"\x1a\x45\xdf\xa3":
                return "webm"
            if data[:4] == b"OggS":
                return "ogv"
            if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"AVI ":
                return "mp4"  # store AVI under a broadly-playable container name
            return None
        # audio
        if data[:3] == b"ID3" or (
            len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
        ):
            return "mp3"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return "wav"
        if data[:4] == b"OggS":
            return "ogg"
        if data[:4] == b"fLaC":
            return "flac"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "m4a"
        return None
