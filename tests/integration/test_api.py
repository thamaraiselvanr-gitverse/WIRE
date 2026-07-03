from wire.api.main import app  # noqa: F401


def test_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "version" in data


def test_brand_endpoint_requires_auth(client):
    # The brand-transfer route must be registered and reject unauthenticated
    # requests (no token) rather than 404.
    response = client.post(
        "/api/projects/1/brand", json={"colors": {"primary": "#000000"}}
    )
    assert response.status_code in (401, 403)


def test_run_id_derivation_matches_storage_naming():
    from wire.api.main_routes import _run_id_for_url

    assert _run_id_for_url("https://www.example.com/path") == "example.com"
    assert _run_id_for_url("http://sub.site.org:8080/") == "sub.site.org_8080"


def test_substitute_endpoint_requires_auth(client):
    response = client.post(
        "/api/projects/1/substitute",
        json={"field_values": {"headline": {"type": "text", "value": "Hi"}}},
    )
    assert response.status_code in (401, 403)
