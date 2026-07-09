"""Phase B API behavior: refresh-token rotation, security headers, latency."""

import uuid
from datetime import datetime, timezone


def _register(client, name="pb"):
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
    return resp.json()


# --- B2: refresh tokens ---------------------------------------------------------


def test_register_and_login_return_refresh_token(client):
    body = _register(client, "rt")
    assert body["refresh_token"]
    assert body["access_token"]


def test_refresh_rotates_and_old_token_dies(client):
    body = _register(client, "rot")
    first = body["refresh_token"]

    r1 = client.post("/api/auth/refresh", json={"refresh_token": first})
    assert r1.status_code == 200
    second = r1.json()["refresh_token"]
    assert second != first

    # The consumed token is single-use: replaying it fails...
    replay = client.post("/api/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401
    # ...while the rotated successor works.
    r2 = client.post("/api/auth/refresh", json={"refresh_token": second})
    assert r2.status_code == 200


def test_logout_revokes_refresh_token(client):
    body = _register(client, "lo")
    token = body["refresh_token"]
    out = client.post("/api/auth/logout", json={"refresh_token": token})
    assert out.status_code == 200 and out.json()["revoked"] is True
    # Revoked -> refresh refused; double-logout is a no-op.
    assert (
        client.post("/api/auth/refresh", json={"refresh_token": token}).status_code
        == 401
    )
    again = client.post("/api/auth/logout", json={"refresh_token": token})
    assert again.json()["revoked"] is False


def test_bogus_refresh_token_rejected(client):
    resp = client.post("/api/auth/refresh", json={"refresh_token": "not-a-token"})
    assert resp.status_code == 401


def test_access_token_expiry_is_tz_aware_and_future(client):
    from jose import jwt

    from wire.api.auth import ALGORITHM, SECRET_KEY

    body = _register(client, "exp")
    payload = jwt.decode(body["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    assert exp > datetime.now(timezone.utc)


# --- B3: security headers -------------------------------------------------------


def test_api_responses_carry_security_headers(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
    # HSTS is opt-in; not asserted here because the test env is plain HTTP.


def test_file_routes_remain_frameable(client):
    # The dashboard embeds /files/*.html previews in an iframe: the global
    # frame denial must not apply there (404 body still carries headers).
    resp = client.get("/api/projects/1/files/index.html")
    assert "x-frame-options" not in resp.headers


# --- B6: request latency histogram ----------------------------------------------


def test_http_latency_histogram_exposed(client):
    client.get("/api/status")
    scrape = client.get("/api/metrics")
    assert scrape.status_code == 200
    assert "wire_http_request_duration_seconds_count" in scrape.text
    assert 'wire_http_request_duration_seconds_bucket{le="+Inf"}' in scrape.text
