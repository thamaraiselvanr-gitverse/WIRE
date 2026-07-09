"""Robots-compliance enforcement and per-user daily quota."""

import pytest

from wire.api.quota import daily_reconstruction_quota
from wire.orchestrator.execution_router import ExecutionRouter
from wire.utils.errors import ComplianceError


def test_check_compliance_blocks_restricted():
    router = ExecutionRouter()
    with pytest.raises(ComplianceError):
        router._check_compliance(
            {"url": "https://x.test", "classification": "restricted"}
        )


def test_check_compliance_allows_safe():
    router = ExecutionRouter()
    # No exception for a safe classification.
    router._check_compliance(
        {"url": "https://x.test", "classification": "safe_to_reconstruct"}
    )


def test_respect_robots_flag_can_disable_enforcement():
    router = ExecutionRouter()
    router.respect_robots = False
    # Even a restricted target passes when enforcement is explicitly disabled.
    router._check_compliance({"url": "https://x.test", "classification": "restricted"})


def test_daily_quota_env(monkeypatch):
    monkeypatch.delenv("WIRE_DAILY_RECONSTRUCTION_QUOTA", raising=False)
    assert daily_reconstruction_quota() == 50
    monkeypatch.setenv("WIRE_DAILY_RECONSTRUCTION_QUOTA", "3")
    assert daily_reconstruction_quota() == 3
    monkeypatch.setenv("WIRE_DAILY_RECONSTRUCTION_QUOTA", "garbage")
    assert daily_reconstruction_quota() == 50
