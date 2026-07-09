"""Phase D: object-storage sync mirrors completed runs (best-effort)."""

import os

from wire.storage.object_sync import ObjectStorageSync


class _FakeS3:
    """Records upload_file calls; can be told to fail specific keys."""

    def __init__(self, fail_keys=frozenset()):
        self.uploads = []
        self.fail_keys = set(fail_keys)

    def upload_file(self, local_path, bucket, key):
        if key in self.fail_keys:
            raise RuntimeError(f"upload failed for {key}")
        self.uploads.append((local_path, bucket, key))


def _make_run(tmp_path):
    run = tmp_path / "project_7"
    (run / "assets").mkdir(parents=True)
    (run / "index.html").write_text("<h1>hi</h1>")
    (run / "schema_cids.json").write_text("{}")
    (run / "assets" / "logo.png").write_bytes(b"\x89PNG")
    return str(run)


def test_enabled_reflects_bucket_env(monkeypatch):
    monkeypatch.delenv("WIRE_S3_BUCKET", raising=False)
    assert ObjectStorageSync.enabled() is False
    monkeypatch.setenv("WIRE_S3_BUCKET", "my-bucket")
    assert ObjectStorageSync.enabled() is True


def test_uploads_every_file_under_prefixed_run_key(tmp_path):
    fake = _FakeS3()
    sync = ObjectStorageSync(bucket="b", prefix="runs", client=fake)
    report = sync.upload_run(_make_run(tmp_path), "project_7")

    assert report["uploaded"] == 3
    assert report["failed"] == 0
    assert report["bytes"] > 0
    keys = sorted(k for _, _, k in fake.uploads)
    assert keys == [
        "runs/project_7/assets/logo.png",
        "runs/project_7/index.html",
        "runs/project_7/schema_cids.json",
    ]
    assert all(bucket == "b" for _, bucket, _ in fake.uploads)


def test_partial_failure_is_counted_not_raised(tmp_path):
    fake = _FakeS3(fail_keys={"runs/project_7/index.html"})
    sync = ObjectStorageSync(bucket="b", prefix="runs", client=fake)
    report = sync.upload_run(_make_run(tmp_path), "project_7")
    # One file failed; the rest still uploaded, and nothing raised.
    assert report["uploaded"] == 2
    assert report["failed"] == 1


def test_no_bucket_is_skipped_not_error(tmp_path):
    sync = ObjectStorageSync(bucket=None, client=_FakeS3())
    report = sync.upload_run(_make_run(tmp_path), "project_7")
    assert report["skipped"] == 1
    assert report["uploaded"] == 0


def test_missing_run_dir_is_skipped(tmp_path):
    sync = ObjectStorageSync(bucket="b", client=_FakeS3())
    report = sync.upload_run(str(tmp_path / "does_not_exist"), "project_9")
    assert report["skipped"] == 1


def test_router_run_dir_name_is_object_key(tmp_path):
    # The pipeline falls back to the run directory's basename as the object
    # key when no explicit run_id was passed (CLI runs).
    from wire.orchestrator.execution_router import ExecutionRouter

    router = ExecutionRouter()
    router.storage.current_run_dir = os.path.join(str(tmp_path), "example.com") + os.sep
    assert router._run_dir_name() == "example.com"


def test_prefix_and_endpoint_read_from_env(monkeypatch):
    monkeypatch.setenv("WIRE_S3_BUCKET", "envbucket")
    monkeypatch.setenv("WIRE_S3_PREFIX", "wire-runs")
    monkeypatch.setenv("WIRE_S3_ENDPOINT_URL", "https://minio.local")
    sync = ObjectStorageSync(client=_FakeS3())
    assert sync.bucket == "envbucket"
    assert sync.prefix == "wire-runs"
    assert sync.endpoint_url == "https://minio.local"
    assert sync._key_for("project_1", os.path.join("assets", "a.png")) == (
        "wire-runs/project_1/assets/a.png"
    )
