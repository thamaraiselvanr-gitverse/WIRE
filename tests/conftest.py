import pytest
from fastapi.testclient import TestClient

from wire.api.main import app


@pytest.fixture
def client():
    # Simple fixture for integration/api tests
    with TestClient(app) as client:
        yield client
