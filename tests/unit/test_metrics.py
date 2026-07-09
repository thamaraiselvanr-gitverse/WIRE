"""Metrics registry + /api/metrics exposition, and Sentry no-op-when-unset."""

from wire.api import metrics


def test_counter_increments_and_registers():
    metrics.reset()
    c = metrics.counter("widgets_total")
    assert c.value == 0
    c.inc()
    c.inc(4)
    assert c.value == 5
    # Same name returns the same counter.
    assert metrics.counter("widgets_total") is c


def test_render_prometheus_format():
    metrics.reset()
    metrics.counter("jobs_completed_total").inc(3)
    text = metrics.render_prometheus()
    assert "# TYPE wire_jobs_completed_total counter" in text
    assert "wire_jobs_completed_total 3" in text
    assert text.endswith("\n")


def test_metrics_endpoint_exposes_counters(client):
    metrics.reset()
    metrics.counter("http_requests_total").inc(2)
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert "wire_http_requests_total 2" in resp.text


def test_reconstruction_request_increments_metric(client, monkeypatch):
    metrics.reset()
    monkeypatch.setattr("wire.utils.url_guard.is_public_http_url", lambda url: True)

    async def _fake(self, url):
        return 0.0

    monkeypatch.setattr(
        "wire.orchestrator.execution_router.ExecutionRouter.execute_pipeline", _fake
    )
    import uuid

    name = f"m_{uuid.uuid4().hex[:8]}"
    reg = client.post(
        "/api/auth/register",
        json={"username": name, "email": f"{name}@ex.com", "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    client.post(
        "/api/projects", json={"url": "https://ok.example.com"}, headers=headers
    )

    assert metrics.counter("reconstructions_requested_total").value >= 1
    assert "wire_reconstructions_requested_total" in client.get("/api/metrics").text


def test_sentry_init_is_noop_without_dsn(monkeypatch):
    # Importing / initializing with no SENTRY_DSN must not raise.
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    from wire.api.main import _init_sentry

    _init_sentry()  # no exception
