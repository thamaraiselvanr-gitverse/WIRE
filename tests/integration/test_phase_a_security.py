"""Phase-A security hardening: scoped tokens, telemetry auth, password policy."""

import os
import uuid

import pytest


def _register(client, name="sec"):
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
    async def _fake(self, url, run_id=None):
        return 0.0

    monkeypatch.setattr(
        "wire.orchestrator.execution_router.ExecutionRouter.execute_pipeline", _fake
    )
    monkeypatch.setattr("wire.utils.url_guard.is_public_http_url", lambda url: True)


# --- Password policy (A5) -----------------------------------------------------


def test_short_password_rejected(client):
    resp = client.post(
        "/api/auth/register",
        json={"username": "shorty1", "email": "s@example.com", "password": "abc12"},
    )
    assert resp.status_code == 422
    assert "8 characters" in resp.text


def test_all_digit_password_rejected(client):
    resp = client.post(
        "/api/auth/register",
        json={"username": "digits1", "email": "d@example.com", "password": "12345678"},
    )
    assert resp.status_code == 422


def test_tiny_username_rejected(client):
    resp = client.post(
        "/api/auth/register",
        json={"username": "ab", "email": "ab@example.com", "password": "secret123"},
    )
    assert resp.status_code == 422


# --- Scoped file tokens (A3) ---------------------------------------------------


def _make_project(client, headers, url="https://scoped.test"):
    resp = client.post("/api/projects", json={"url": url}, headers=headers)
    assert resp.status_code == 200
    return resp.json()["project_id"]


def test_file_token_requires_ownership(client):
    owner = {"Authorization": f"Bearer {_register(client, 'owner')}"}
    intruder = {"Authorization": f"Bearer {_register(client, 'intruder')}"}
    pid = _make_project(client, owner)

    assert (
        client.get(f"/api/projects/{pid}/file-token", headers=owner).status_code == 200
    )
    assert (
        client.get(f"/api/projects/{pid}/file-token", headers=intruder).status_code
        == 404
    )
    assert client.get(f"/api/projects/{pid}/file-token").status_code == 401


def test_file_token_is_bound_to_its_project(client, tmp_path):
    headers = {"Authorization": f"Bearer {_register(client, 'binder')}"}
    pid_a = _make_project(client, headers, "https://a.test")
    pid_b = _make_project(client, headers, "https://b.test")

    run_dir = os.path.join("output", f"project_{pid_b}")
    os.makedirs(run_dir, exist_ok=True)
    target = os.path.join(run_dir, "index.html")
    try:
        with open(target, "w") as f:
            f.write("<h1>b</h1>")

        token_a = client.get(
            f"/api/projects/{pid_a}/file-token", headers=headers
        ).json()["file_token"]
        token_b = client.get(
            f"/api/projects/{pid_b}/file-token", headers=headers
        ).json()["file_token"]

        # Token for A cannot open B's files, even for the same owner.
        cross = client.get(f"/api/projects/{pid_b}/files/index.html?token={token_a}")
        assert cross.status_code == 401
        ok = client.get(f"/api/projects/{pid_b}/files/index.html?token={token_b}")
        assert ok.status_code == 200
    finally:
        if os.path.exists(target):
            os.remove(target)


def test_served_html_is_csp_sandboxed(client, tmp_path):
    # Reconstructed pages are untrusted third-party content; the browser must
    # render them script-less in an opaque origin.
    headers = {"Authorization": f"Bearer {_register(client, 'csp')}"}
    pid = _make_project(client, headers, "https://csp.test")
    run_dir = os.path.join("output", f"project_{pid}")
    os.makedirs(os.path.join(run_dir, "assets"), exist_ok=True)
    html = os.path.join(run_dir, "index.html")
    png = os.path.join(run_dir, "assets", "x.png")
    try:
        with open(html, "w") as f:
            f.write("<script>alert(1)</script>")
        with open(png, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")

        page = client.get(f"/api/projects/{pid}/files/index.html", headers=headers)
        assert page.status_code == 200
        assert page.headers.get("content-security-policy") == "sandbox"
        assert page.headers.get("x-content-type-options") == "nosniff"

        asset = client.get(f"/api/projects/{pid}/files/assets/x.png", headers=headers)
        assert asset.status_code == 200
        assert "content-security-policy" not in asset.headers
    finally:
        for p in (html, png):
            if os.path.exists(p):
                os.remove(p)


# --- Telemetry stream auth (A2) -------------------------------------------------


def test_telemetry_requires_token(client):
    assert client.get("/api/projects/telemetry").status_code == 401


def test_telemetry_rejects_session_token_in_query(client):
    token = _register(client, "sse")
    resp = client.get(f"/api/projects/telemetry?token={token}")
    assert resp.status_code == 401


def test_stream_token_requires_auth_and_is_scoped(client):
    assert client.get("/api/auth/stream-token").status_code == 401
    token = _register(client, "sse2")
    resp = client.get(
        "/api/auth/stream-token", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stream_token"] and body["expires_in"] == 900

    # A telemetry-scoped token cannot open project files.
    from fastapi import HTTPException

    from wire.api.auth import decode_scoped_token

    with pytest.raises(HTTPException):
        decode_scoped_token(body["stream_token"], expected_scope="files")
