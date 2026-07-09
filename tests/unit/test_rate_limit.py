"""In-process rate limiter + API enforcement."""

import pytest
from fastapi import HTTPException

from wire.api.rate_limit import RateLimiter


def test_allows_up_to_limit_then_blocks():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        rl.check("k")  # first 3 ok
    with pytest.raises(HTTPException) as exc:
        rl.check("k")  # 4th blocked
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


def test_keys_are_independent():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    rl.check("a")
    rl.check("b")  # different key, still ok
    with pytest.raises(HTTPException):
        rl.check("a")


def test_window_expiry_allows_again():
    rl = RateLimiter(max_requests=1, window_seconds=0.05)
    rl.check("k")
    with pytest.raises(HTTPException):
        rl.check("k")
    import time

    time.sleep(0.06)
    rl.check("k")  # window elapsed -> allowed again


def test_reset_clears_state():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    rl.check("k")
    rl.reset()
    rl.check("k")  # reset cleared the window


def test_api_reconstruction_rate_limited(client, monkeypatch):
    # Allow-all SSRF + stub pipeline so we isolate the rate limiter.
    monkeypatch.setattr("wire.utils.url_guard.is_public_http_url", lambda url: True)

    async def _fake(self, url):
        return 0.0

    monkeypatch.setattr(
        "wire.orchestrator.execution_router.ExecutionRouter.execute_pipeline", _fake
    )
    # Tighten the limit for the test (monkeypatch auto-restores after).
    from wire.api.rate_limit import reconstruction_limiter

    monkeypatch.setattr(reconstruction_limiter, "max_requests", 2)
    reconstruction_limiter.reset()

    reg = client.post(
        "/api/auth/register",
        json={
            "username": "rluser",
            "email": "rl@example.com",
            "password": "secret123",
        },
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    codes = [
        client.post(
            "/api/projects", json={"url": "https://ok.example.com"}, headers=headers
        ).status_code
        for _ in range(3)
    ]
    assert codes[:2] == [200, 200]
    assert codes[2] == 429
