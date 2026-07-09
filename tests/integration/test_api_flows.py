import uuid


def _register(client):
    username = "u" + uuid.uuid4().hex[:10]
    resp = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "secret123",
        },
    )
    assert resp.status_code == 200, resp.text
    return username, resp.json()["access_token"]


def test_register_login_and_list_projects(client):
    username, token = _register(client)

    # Duplicate registration is rejected.
    dup = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "secret123",
        },
    )
    assert dup.status_code == 400

    # Login with correct + wrong password.
    ok = client.post(
        "/api/auth/login", data={"username": username, "password": "secret123"}
    )
    assert ok.status_code == 200
    bad = client.post(
        "/api/auth/login", data={"username": username, "password": "wrong"}
    )
    assert bad.status_code == 401

    # Authenticated project listing (empty for a fresh user).
    headers = {"Authorization": f"Bearer {token}"}
    projects = client.get("/api/projects", headers=headers)
    assert projects.status_code == 200
    assert projects.json() == []


def test_project_endpoints_require_auth(client):
    # No token -> rejected.
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/projects/1/brand", json={"colors": {}}).status_code == 401
    assert (
        client.post("/api/projects/1/substitute", json={"field_values": {}}).status_code
        == 401
    )


def test_brand_and_substitute_404_for_unknown_project(client):
    _, token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post(
        "/api/projects/999999/brand",
        json={"colors": {"primary": "#000000"}},
        headers=headers,
    )
    assert r1.status_code == 404

    r2 = client.post(
        "/api/projects/999999/substitute",
        json={"field_values": {"x": {"type": "text", "value": "hi"}}},
        headers=headers,
    )
    assert r2.status_code == 404


def test_file_endpoint_missing_token_401(client):
    assert client.get("/api/projects/1/files/index.html").status_code == 401
