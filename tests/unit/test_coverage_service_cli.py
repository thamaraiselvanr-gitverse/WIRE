import wire.main as wire_main
from wire.utils.logging import setup_logging, sse_event_broadcaster


def test_setup_logging_and_broadcaster_are_safe():
    setup_logging()  # must not raise
    # The broadcaster returns the event dict unchanged and never raises even if
    # the API queue module is importable/empty.
    event = {"event": "hello", "level": "info", "answer": 42}
    assert sse_event_broadcaster(None, "info", event) is event


def test_broadcaster_pushes_to_queues(monkeypatch):
    import wire.api.main_routes as mr

    q = __import__("asyncio").Queue()
    monkeypatch.setattr(mr, "log_event_queues", [q])
    sse_event_broadcaster(None, "info", {"event": "boom", "level": "warning", "x": 1})
    assert not q.empty()
    msg = q.get_nowait()
    assert "boom" in msg and "x=1" in msg


def test_service_run_delegates_to_router(monkeypatch):
    from wire.service import WireService

    async def fake_pipeline(url):
        return 87.5

    svc = WireService()
    monkeypatch.setattr(svc.router, "execute_pipeline", fake_pipeline)
    import asyncio

    assert asyncio.run(svc.run("http://x")) == 87.5


def test_cli_main_runs_url(monkeypatch, capsys):
    # Stub the service so no real pipeline/browser is launched.
    class FakeService:
        async def run(self, url):
            return 91.0

    monkeypatch.setattr(wire_main, "WireService", FakeService)
    monkeypatch.setattr(wire_main.sys, "argv", ["wire", "http://example.com"])
    wire_main.main()
    out = capsys.readouterr().out
    assert "Fidelity Score: 91.0" in out


def test_cli_main_usage_without_args(monkeypatch, capsys):
    # No args -> prints usage then would start server; stub uvicorn.run.
    started = {}
    monkeypatch.setattr(wire_main.sys, "argv", ["wire"])
    monkeypatch.setattr(
        wire_main.uvicorn, "run", lambda *a, **k: started.update({"ran": True})
    )
    wire_main.main()
    assert started.get("ran")
    assert "Usage" in capsys.readouterr().out
