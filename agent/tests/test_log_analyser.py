import sys
import os
# Add parent directory to path so imports work cleanly in test suite
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch
from state import Alert, AgentState
from tools.k8s_log_tools import get_pod_logs
from agents.log_analyser import log_analyser_node

def test_get_pod_logs_tool():
    # Test high-fidelity mock log generation
    res_backend = get_pod_logs.func(**{"service_name": "backend"})
    assert "sqlalchemy.exc.OperationalError" in res_backend
    assert "Connection timed out" in res_backend
    
    res_frontend = get_pod_logs.func(**{"service_name": "frontend"})
    assert "Event loop blocked" in res_frontend
    assert "504 Gateway Timeout" in res_frontend
    
    res_db = get_pod_logs.func(**{"service_name": "database-stub"})
    assert "OOM-killer triggered" in res_db
    
    res_fallback = get_pod_logs.func(**{"service_name": "unknown-service"})
    assert "GET /health" in res_fallback

@pytest.mark.asyncio
async def test_log_analyser_node_mock_path(monkeypatch):
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
    
    state: AgentState = {
        "incident_id": "inc-123",
        "alert": alert,
        "detective_findings": None,
        "topologist_findings": None,
        "historian_findings": None,
        "log_findings": None,
        "hypothesis": None,
        "confidence": None,
        "recommended_action": None,
        "requires_human_approval": False
    }
    
    res = await log_analyser_node(state)
    assert "log_findings" in res
    findings = res["log_findings"]
    assert "psycopg2.OperationalError" in findings["error_logs"][0]
    assert findings["suspect_stack_trace"] is not None
    assert "connection pooling" in findings["reasoning"].lower()

