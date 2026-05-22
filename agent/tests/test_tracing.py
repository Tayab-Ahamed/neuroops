import pytest
import asyncio
from unittest.mock import MagicMock, patch
from tracing import traced_node, llm_retry, tracer

@pytest.mark.asyncio
async def test_traced_node_success_dict():
    # Test when function returns a dictionary representing findings
    @traced_node("test_agent")
    async def mock_node(state):
        return {
            "test_agent_findings": {
                "hypothesis": "database breakdown",
                "confidence": 0.85,
                "requires_human_approval": True
            }
        }
    
    state = {"incident_id": "inc-123"}
    res = await mock_node(state)
    assert res["test_agent_findings"]["hypothesis"] == "database breakdown"

@pytest.mark.asyncio
async def test_traced_node_success_flat_dict():
    # Test when findings are flat in the returned dictionary
    @traced_node("test_agent")
    async def mock_node(state):
        return {
            "likely_origin": "backend",
            "confidence": 0.75,
            "requires_human_approval": False
        }
    
    state = {"incident_id": "inc-123"}
    res = await mock_node(state)
    assert res["likely_origin"] == "backend"

@pytest.mark.asyncio
async def test_traced_node_success_non_dict():
    @traced_node("test_agent")
    async def mock_node(state):
        return "non-dict-result"
    
    state = {}
    res = await mock_node(state)
    assert res == "non-dict-result"

@pytest.mark.asyncio
async def test_traced_node_exception():
    @traced_node("test_agent")
    async def mock_node(state):
        raise ValueError("simulated error")
    
    state = {"incident_id": "inc-123"}
    with pytest.raises(ValueError, match="simulated error"):
        await mock_node(state)

@pytest.mark.asyncio
async def test_llm_retry_success():
    call_count = 0
    
    @llm_retry
    async def failing_then_succeeding():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise RuntimeError("Temporary error")
        return "success"
        
    res = await failing_then_succeeding()
    assert res == "success"
    assert call_count == 2

@pytest.mark.asyncio
async def test_llm_retry_failure():
    call_count = 0
    
    @llm_retry
    async def always_failing():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Persistent error")
        
    with patch("tenacity.nap.time.sleep", return_value=None):
        with pytest.raises(RuntimeError, match="Persistent error"):
            await always_failing()
    assert call_count == 3
