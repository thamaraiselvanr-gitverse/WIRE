import pytest
from fastapi.testclient import TestClient

from wire.api.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    # The whole suite hits the API from one TestClient IP; clear the in-memory
    # limiter windows before each test so per-IP/user budgets don't bleed across
    # tests. The dedicated rate-limit test exercises the limit within one test.
    from wire.api.rate_limit import auth_limiter, reconstruction_limiter

    auth_limiter.reset()
    reconstruction_limiter.reset()
    yield


@pytest.fixture
def client():
    # Simple fixture for integration/api tests
    with TestClient(app) as client:
        yield client
