import pytest
import os
from unittest.mock import MagicMock, patch
from state import Alert, AgentState
from graph import graph, route_based_on_confidence

@pytest.mark.asyncio
async def test_route_based_on_confidence():
    # 1. Low confidence -> escalate
    state_low: AgentState = {"confidence": 0.5, "requires_human_approval": False}
    assert route_based_on_confidence(state_low) == "escalate"
    
    # 2. High confidence but requires approval -> escalate
    state_approval: AgentState = {"confidence": 0.8, "requires_human_approval": True}
    assert route_based_on_confidence(state_approval) == "escalate"
    
    # 3. High confidence, no approval -> remediate
    state_ok: AgentState = {"confidence": 0.8, "requires_human_approval": False}
    assert route_based_on_confidence(state_ok) == "remediate"

@pytest.mark.asyncio
async def test_full_graph_execution_mock_path(monkeypatch):
    # Ensure no API keys are set to force mock paths inside nodes
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu_usage": 92.5, "memory_usage": 78.0},
        anomaly_score=-0.45
    )
    
    initial_state: AgentState = {
        "incident_id": "",
        "alert": alert,
        "detective_findings": None,
        "topologist_findings": None,
        "historian_findings": None,
        "hypothesis": None,
        "confidence": None,
        "recommended_action": None,
        "requires_human_approval": False
    }
    
    final_state = await graph.ainvoke(initial_state, config={"configurable": {"thread_id": "test-thread"}})
    
    # Assert nodes ran and updated state
    assert final_state["incident_id"].startswith("inc-")
    assert final_state["detective_findings"]["likely_origin"] == "backend"
    assert final_state["topologist_findings"]["bottleneck"] == "backend"
    assert final_state["historian_findings"]["suspect_commit"] == "a1b2c3d4e5f6"
    assert final_state["confidence"] == 0.85
    assert final_state["recommended_action"] == "rollback"
    assert final_state["requires_human_approval"] is True

@pytest.mark.asyncio
async def test_remediation_path(monkeypatch):
    import importlib
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    import agents.historian
    import graph
    
    async def mock_historian(state):
        return {"historian_findings": {}}
        
    with patch("agents.historian.historian_node", side_effect=mock_historian):
        importlib.reload(graph)
        
        alert = Alert(
            id="alert-111",
            service="backend",
            severity="P2",
            timestamp=1716390000.0,
            metric_snapshot={"cpu_usage": 92.5, "memory_usage": 78.0},
            anomaly_score=-0.45
        )
        
        initial_state: AgentState = {
            "incident_id": "",
            "alert": alert,
            "detective_findings": None,
            "topologist_findings": None,
            "historian_findings": None,
            "hypothesis": None,
            "confidence": None,
            "recommended_action": None,
            "requires_human_approval": False
        }
        
        final_state = await graph.graph.ainvoke(initial_state, config={"configurable": {"thread_id": "test-thread-rem"}})
        
        assert final_state["confidence"] == 0.70
        assert final_state["recommended_action"] == "restart"
        assert final_state["requires_human_approval"] is False

    # Restore the original graph compilation
    importlib.reload(graph)
