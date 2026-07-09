"""Optional object-storage sync for completed reconstruction runs.

The pipeline writes artifacts to local disk (a browser needs a real filesystem,
and every stage reads/writes ``output/<run>/`` directly). For durability and
disaster recovery across ephemeral/replaced hosts, a completed run directory is
mirrored to an S3-compatible bucket when ``WIRE_S3_BUCKET`` is configured.

This is deliberately a *post-run mirror*, not an object-store-native
filesystem: local scratch stays the source of truth during a run, and the
upload is best-effort — a sync failure logs and is counted but never fails the
reconstruction (the artifacts still exist locally and are served from there).
Making file *serving* read from object storage is a separate, larger change
(see the deferred item in the readiness report).

Works with AWS S3 and any S3-compatible endpoint (MinIO, R2, Spaces) via
``WIRE_S3_ENDPOINT_URL``. Credentials come from the standard AWS environment/
instance mechanisms (never committed).
"""

import os
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class ObjectStorageSync:
    """Mirror a local run directory to an S3-compatible bucket."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: str = "",
        client: Optional[Any] = None,
        endpoint_url: Optional[str] = None,
    ) -> None:
        self.bucket = bucket if bucket is not None else os.environ.get("WIRE_S3_BUCKET")
        self.prefix = (prefix or os.environ.get("WIRE_S3_PREFIX", "runs")).strip("/")
        self.endpoint_url = endpoint_url or os.environ.get("WIRE_S3_ENDPOINT_URL")
        self._client = client

    @classmethod
    def enabled(cls) -> bool:
        """True when object-storage sync is configured for this deployment."""
        return bool(os.environ.get("WIRE_S3_BUCKET"))

    def _s3(self) -> Any:
        if self._client is None:
            import boto3  # optional dependency; only imported when configured

            self._client = boto3.client("s3", endpoint_url=self.endpoint_url)
        return self._client

    def _key_for(self, run_id: str, rel_path: str) -> str:
        parts = [p for p in (self.prefix, run_id, rel_path) if p]
        return "/".join(parts).replace(os.sep, "/")

    def upload_run(self, run_dir: str, run_id: str) -> Dict[str, Any]:
        """Upload every file under ``run_dir`` to ``bucket/prefix/run_id/…``.

        Returns a report ``{uploaded, failed, bytes, skipped}``. Best-effort:
        individual file failures are counted, not raised, and a missing bucket
        config or unreachable endpoint yields ``skipped`` rather than an error
        — the local artifacts remain the served source of truth.
        """
        report: Dict[str, Any] = {"uploaded": 0, "failed": 0, "bytes": 0, "skipped": 0}
        if not self.bucket:
            report["skipped"] = 1
            logger.info("object_sync_skipped_no_bucket", run_id=run_id)
            return report
        if not os.path.isdir(run_dir):
            report["skipped"] = 1
            logger.warning("object_sync_skipped_no_dir", run_dir=run_dir)
            return report

        try:
            client = self._s3()
        except Exception as e:  # pragma: no cover - import/credential failure
            report["skipped"] = 1
            logger.warning("object_sync_client_unavailable", error=str(e))
            return report

        for root, _dirs, files in os.walk(run_dir):
            for name in files:
                local_path = os.path.join(root, name)
                rel_path = os.path.relpath(local_path, run_dir)
                key = self._key_for(run_id, rel_path)
                try:
                    client.upload_file(local_path, self.bucket, key)
                    report["uploaded"] += 1
                    report["bytes"] += os.path.getsize(local_path)
                except Exception as e:
                    report["failed"] += 1
                    logger.warning("object_sync_file_failed", key=key, error=str(e))
        logger.info(
            "object_sync_complete",
            run_id=run_id,
            uploaded=report["uploaded"],
            failed=report["failed"],
            bytes=report["bytes"],
        )
        return report
