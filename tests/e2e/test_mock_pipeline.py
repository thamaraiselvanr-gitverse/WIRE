import pytest
from wire.orchestrator.execution_router import ExecutionRouter
import os

@pytest.mark.asyncio
async def test_end_to_end_mock_pipeline(tmp_path):
    # This simulates a mock execution router running against a safe local target 
    # instead of a live domain, ensuring deterministic CI runs.
    
    # We would boot a local HTTP server fixture here. For now, we instantiate 
    # the router and ensure it imports without dependency failures.
    router = ExecutionRouter()
    
    # Temporarily override storage dir
    router.storage.base_dir = str(tmp_path)
    
    # Assert successful orchestration instantiation
    assert router.crawler is not None
    assert router.scorer.base_score == 100.0
