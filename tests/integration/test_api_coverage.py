"""Coverage-focused API tests: project lifecycle, brand/substitute error paths,
authenticated file serving, and auth edge cases — all without a real browser
(the background pipeline is stubbed)."""

import os
import uuid

import pytest

from wire.api.auth import create_access_token
from wire.api.main_routes import _run_id_for_url


def _register(client, name="covuser"):
    # Unique per call — the integration DB (SQLite file) persists across tests.
    uniq = f"{name}_{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/auth/register",
        json={
            "username": uniq,
            "email": f"{uniq}@example.com",
            "password": "secret123",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(autouse=True)
def _stub_pipeline(monkeypatch):
    # Keep the background reconstruction from launching a real browser.
    async def _fake(self, url):
        return 0.0

    monkeypatch.setattr(
        "wire.orchestrator.execution_router.ExecutionRouter.execute_pipeline", _fake
    )
    # Allow the reserved .test domains these tests use past the SSRF guard;
    # the guard itself is exercised in test_url_guard and the dedicated test below.
    monkeypatch.setattr("wire.utils.url_guard.is_public_http_url", lambda url: True)


def test_run_id_for_url_local_file_fallback():
    # No netloc -> derive from the path basename (stripped of extension).
    assert _run_id_for_url("file:///tmp/site.html") == "site"
    assert _run_id_for_url("file:///") == "local"


def test_start_reconstruction_creates_project(client):
    token = _register(client, "starter")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/api/projects", json={"url": "https://example.com"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] >= 1
    assert "queued" in body["message"].lower()

    # The new project shows up in the owner's list.
    listing = client.get("/api/projects", headers=headers)
    assert listing.status_code == 200
    assert any(p["url"] == "https://example.com" for p in listing.json())


def test_brand_on_owned_project_without_stored_run_400(client):
    token = _register(client, "brander")
    headers = {"Authorization": f"Bearer {token}"}
    pid = client.post(
        "/api/projects", json={"url": "https://brand.test"}, headers=headers
    ).json()["project_id"]
    # Project exists and is owned, but no reconstruction run is stored -> 400.
    resp = client.post(
        f"/api/projects/{pid}/brand",
        json={"colors": {"primary": "#123456"}},
        headers=headers,
    )
    assert resp.status_code == 400


def test_substitute_invalid_payload_422_and_missing_run_400(client):
    token = _register(client, "subber")
    headers = {"Authorization": f"Bearer {token}"}
    pid = client.post(
        "/api/projects", json={"url": "https://sub.test"}, headers=headers
    ).json()["project_id"]

    # Malformed value dict -> payload validation fails -> 422.
    bad = client.post(
        f"/api/projects/{pid}/substitute",
        json={"field_values": {"x": {"type": "nonsense"}}},
        headers=headers,
    )
    assert bad.status_code == 422

    # Valid payload but no stored run -> 400.
    ok = client.post(
        f"/api/projects/{pid}/substitute",
        json={"field_values": {"headline": {"type": "text", "value": "Hi"}}},
        headers=headers,
    )
    assert ok.status_code == 400


def test_file_serving_paths(client, tmp_path, monkeypatch):
    token = _register(client, "filer")
    headers = {"Authorization": f"Bearer {token}"}
    pid = client.post(
        "/api/projects", json={"url": "https://files.test"}, headers=headers
    ).json()["project_id"]
    host = _run_id_for_url("https://files.test")

    # Unknown file -> 404 (authenticated).
    missing = client.get(f"/api/projects/{pid}/files/nope.html", headers=headers)
    assert missing.status_code == 404

    # Create real run output and fetch both a top-level file and an asset.
    run_dir = os.path.join("output", host)
    assets_dir = os.path.join(run_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    try:
        with open(os.path.join(run_dir, "index.html"), "w") as f:
            f.write("<h1>hi</h1>")
        with open(os.path.join(assets_dir, "logo.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")

        # Top-level file via query-param token (img/iframe style).
        top = client.get(f"/api/projects/{pid}/files/index.html?token={token}")
        assert top.status_code == 200

        # Asset path routes into assets/.
        asset = client.get(
            f"/api/projects/{pid}/files/assets/logo.png", headers=headers
        )
        assert asset.status_code == 200
    finally:
        for p in (
            os.path.join(assets_dir, "logo.png"),
            os.path.join(run_dir, "index.html"),
        ):
            if os.path.exists(p):
                os.remove(p)


def test_file_serving_rejects_missing_and_bad_tokens(client):
    # No token at all -> 401.
    assert client.get("/api/projects/1/files/index.html").status_code == 401
    # Malformed bearer token -> 401.
    bad = client.get(
        "/api/projects/1/files/index.html",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert bad.status_code == 401


def test_protected_route_rejects_token_without_subject(client):
    # A validly-signed token missing "sub" must be rejected.
    token = create_access_token(data={})
    resp = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_login_unknown_user_401(client):
    resp = client.post(
        "/api/auth/login", data={"username": "ghost", "password": "whatever"}
    )
    assert resp.status_code == 401


def test_start_reconstruction_rejects_ssrf_url(client, monkeypatch):
    # Override the autouse allow-all so the real guard verdict reaches the route.
    monkeypatch.setattr("wire.utils.url_guard.is_public_http_url", lambda url: False)
    token = _register(client, "ssrf")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/api/projects", json={"url": "http://169.254.169.254/"}, headers=headers
    )
    assert resp.status_code == 400
    assert "public http" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_start_reconstruction_enqueues_durable_job(client):
    # Creating a project persists a pending job that a worker later drains,
    # rather than firing a task that would be lost on restart.
    from wire import worker
    from wire.api.database import AsyncSessionLocal
    from wire.api.models import Project

    token = _register(client, "queue")
    headers = {"Authorization": f"Bearer {token}"}
    pid = client.post(
        "/api/projects", json={"url": "https://queued.test"}, headers=headers
    ).json()["project_id"]

    async with AsyncSessionLocal() as db:
        assert (await db.get(Project, pid)).status == "pending"

    # Drain the queue with a stubbed pipeline; this project ends up completed.
    async def _ok(url):
        return 91.0

    for _ in range(25):
        if not await worker.process_one(AsyncSessionLocal, _ok):
            break

    async with AsyncSessionLocal() as db:
        assert (await db.get(Project, pid)).status == "completed"


def test_daily_quota_enforced(client, monkeypatch):
    monkeypatch.setattr("wire.api.quota.daily_reconstruction_quota", lambda: 1)
    token = _register(client, "quota")
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/api/projects", json={"url": "https://a.example.com"}, headers=headers
    )
    assert first.status_code == 200
    # Second within the day exceeds the quota of 1.
    second = client.post(
        "/api/projects", json={"url": "https://b.example.com"}, headers=headers
    )
    assert second.status_code == 429
    assert "quota" in second.json()["detail"].lower()


def test_file_route_valid_token_but_deleted_user_401(client, monkeypatch):
    # A validly-signed token whose subject no longer exists -> 401.
    from wire.api.auth import create_access_token

    ghost = create_access_token(data={"sub": "no_such_user_xyz"})
    resp = client.get(
        "/api/projects/1/files/index.html",
        headers={"Authorization": f"Bearer {ghost}"},
    )
    assert resp.status_code == 401
