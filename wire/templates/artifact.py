import hashlib
import json
import os
import zipfile
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class WireArtifact:
    """Cryptographically verifiable ``.wire`` artifact format.

    Packages a reconstruction directory into a single zip with a manifest of
    per-file SHA-256 checksums, enabling tamper-evident verification and
    portable extraction across environments.
    """

    MANIFEST_NAME = "wire_manifest.json"

    @staticmethod
    def _sha256_bytes(data: bytes) -> str:
        h = hashlib.sha256()
        h.update(data)
        return h.hexdigest()

    @classmethod
    def package(
        cls,
        source_dir: str,
        output_file: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        metadata = metadata or {}
        output_abspath = os.path.abspath(output_file)

        files: Dict[str, str] = {}
        payload: Dict[str, bytes] = {}
        for root, _, filenames in os.walk(source_dir):
            for name in filenames:
                abs_path = os.path.join(root, name)
                # Never package the manifest, prior .wire artifacts, or the
                # artifact currently being written (it lives under source_dir).
                if name == cls.MANIFEST_NAME or name.endswith(".wire"):
                    continue
                if os.path.abspath(abs_path) == output_abspath:
                    continue
                rel = os.path.relpath(abs_path, source_dir).replace(os.sep, "/")
                with open(abs_path, "rb") as f:
                    data = f.read()
                payload[rel] = data
                files[rel] = cls._sha256_bytes(data)

        manifest = {"metadata": metadata, "files": files}

        os.makedirs(os.path.dirname(output_abspath) or ".", exist_ok=True)
        with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, data in payload.items():
                z.writestr(rel, data)
            z.writestr(cls.MANIFEST_NAME, json.dumps(manifest, indent=2, default=str))

        logger.info("wire_artifact_packaged", output=output_file, files=len(files))
        return output_file

    @classmethod
    def verify(cls, artifact_file: str) -> Dict[str, Any]:
        errors = []
        try:
            with zipfile.ZipFile(artifact_file, "r") as z:
                names = set(z.namelist())
                if cls.MANIFEST_NAME not in names:
                    return {
                        "valid": False,
                        "files_checked": 0,
                        "errors": ["Missing manifest"],
                        "metadata": {},
                    }
                manifest = json.loads(z.read(cls.MANIFEST_NAME).decode("utf-8"))
                files = manifest.get("files", {})
                for rel, expected in files.items():
                    if rel not in names:
                        errors.append(f"Missing file: {rel}")
                        continue
                    actual = cls._sha256_bytes(z.read(rel))
                    if actual != expected:
                        errors.append(f"Checksum mismatch: {rel}")
        except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as e:
            return {
                "valid": False,
                "files_checked": 0,
                "errors": [f"Artifact unreadable: {e}"],
                "metadata": {},
            }

        return {
            "valid": len(errors) == 0,
            "files_checked": len(files),
            "errors": errors,
            "metadata": manifest.get("metadata", {}),
        }

    @classmethod
    def extract(cls, artifact_file: str, dest_dir: str) -> str:
        os.makedirs(dest_dir, exist_ok=True)
        with zipfile.ZipFile(artifact_file, "r") as z:
            for name in z.namelist():
                if name == cls.MANIFEST_NAME:
                    continue
                # Guard against path traversal in member names.
                target = os.path.join(dest_dir, name)
                abs_target = os.path.abspath(target)
                if not abs_target.startswith(os.path.abspath(dest_dir) + os.sep):
                    logger.warning("skipping_unsafe_member", name=name)
                    continue
                os.makedirs(os.path.dirname(abs_target) or dest_dir, exist_ok=True)
                with z.open(name) as src, open(abs_target, "wb") as out:
                    out.write(src.read())
        logger.info("wire_artifact_extracted", dest=dest_dir)
        return dest_dir
