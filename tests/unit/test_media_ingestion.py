import base64
import os
import tempfile

import pytest

from wire.generation.media_ingestion import MediaIngestionPipeline


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
MP3 = b"ID3\x03\x00" + b"\x00" * 32
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 16


def test_video_ingestion_mp4():
    with tempfile.TemporaryDirectory() as d:
        assets = os.path.join(d, "assets")
        os.makedirs(assets)
        res = MediaIngestionPipeline.process(_b64(MP4), assets, kind="video")
        assert res["content_type"] == "video/mp4"
        assert res["stored_path"].startswith("assets/user_uploads/")
        assert os.path.exists(os.path.join(d, res["stored_path"]))


def test_video_ingestion_webm():
    with tempfile.TemporaryDirectory() as d:
        assets = os.path.join(d, "assets")
        os.makedirs(assets)
        res = MediaIngestionPipeline.process(_b64(WEBM), assets, kind="video")
        assert res["content_type"] == "video/webm"


def test_audio_ingestion_mp3_and_wav():
    with tempfile.TemporaryDirectory() as d:
        assets = os.path.join(d, "assets")
        os.makedirs(assets)
        mp3 = MediaIngestionPipeline.process(_b64(MP3), assets, kind="audio")
        wav = MediaIngestionPipeline.process(_b64(WAV), assets, kind="audio")
        assert mp3["content_type"] == "audio/mpeg"
        assert wav["content_type"] == "audio/wav"


def test_bad_magic_bytes_rejected():
    with tempfile.TemporaryDirectory() as d:
        assets = os.path.join(d, "assets")
        os.makedirs(assets)
        with pytest.raises(ValueError, match="Magic-byte"):
            MediaIngestionPipeline.process(_b64(b"not media"), assets, kind="video")


def test_oversize_rejected():
    with tempfile.TemporaryDirectory() as d:
        assets = os.path.join(d, "assets")
        os.makedirs(assets)
        with pytest.raises(ValueError, match="exceeds the limit"):
            MediaIngestionPipeline.process(
                _b64(MP4), assets, kind="video", max_size_bytes=4
            )


def test_kind_mismatch_rejected():
    with tempfile.TemporaryDirectory() as d:
        assets = os.path.join(d, "assets")
        os.makedirs(assets)
        # An mp3 offered as a video must fail magic-byte detection.
        with pytest.raises(ValueError):
            MediaIngestionPipeline.process(_b64(MP3), assets, kind="video")
