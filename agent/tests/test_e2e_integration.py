"""End-to-end integration tests for the NeuroOps agent graph pipeline.

These tests exercise the full flow without real LLM/K8s/GitHub calls:
  Alert -> supervisor_init -> [detective, topologist, historian, log_analyser] -> supervisor_synthesize -> output
"""

from unittest.mock import MagicMock, patch

import pytest
from state import Alert


def make_alert(
    service="backend",
    severity="P1",
    anomaly_score=-0.89,
    metric_snapshot=None,
):
    """Build a minimal Alert for testing."""
    return Alert(
        id="alert-e2e-001",
        service=service,
        severity=severity,
        timestamp=1716390000.0,
        metric_snapshot=metric_snapshot or {"cpu_usage": 0.92, "error_rate": 0.18},
        anomaly_score=anomaly_score,
    )


def make_initial_state(alert: Alert) -> dict:
    """Build a minimal initial AgentState for testing."""
    return {
        "incident_id": None,
        "alert": alert,
        "detective_findings": None,
        "topologist_findings": None,
        "historian_findings": None,
        "log_findings": None,
        "hypothesis": None,
        "confidence": None,
        "recommended_action": None,
        "requires_human_approval": False,
        "reasoning": None,
        "tokens_used": 0,
        "execute_remediation": False,
        "remediation_result": None,
        "similar_incidents": [],
        "complexity_score": 0.5,
    }


def test_alert_model_validation():
    """Alert model correctly validates field types."""
    alert = make_alert()
    assert alert.service == "backend"
    assert alert.severity == "P1"
    assert alert.anomaly_score == -0.89
    assert isinstance(alert.metric_snapshot, dict)


def test_alert_p2_validation():
    """Alert model works for P2 severity."""
    alert = make_alert(service="frontend", severity="P2", anomaly_score=-0.55)
    assert alert.severity == "P2"
    assert alert.service == "frontend"


def test_initial_state_structure():
    """Initial AgentState has all required keys."""
    alert = make_alert()
    state = make_initial_state(alert)
    required_keys = [
        "incident_id",
        "alert",
        "detective_findings",
        "topologist_findings",
        "historian_findings",
        "log_findings",
        "hypothesis",
        "confidence",
        "recommended_action",
        "requires_human_approval",
        "reasoning",
        "tokens_used",
        "execute_remediation",
        "remediation_result",
        "similar_incidents",
        "complexity_score",
    ]
    for key in required_keys:
        assert key in state, f"Missing key: {key}"


def test_initial_state_defaults():
    """Initial state has correct default values."""
    alert = make_alert()
    state = make_initial_state(alert)
    assert state["incident_id"] is None
    assert state["hypothesis"] is None
    assert state["confidence"] is None
    assert state["requires_human_approval"] is False
    assert state["execute_remediation"] is False
    assert state["similar_incidents"] == []


@pytest.mark.asyncio
async def test_supervisor_init_node_assigns_incident_id():
    """supervisor_init_node should generate an incident_id if none provided."""
    from agents.supervisor import supervisor_init_node

    alert = make_alert(severity="P2", anomaly_score=-0.50)
    state = make_initial_state(alert)
    result = await supervisor_init_node(state)
    assert "incident_id" in result
    assert result["incident_id"].startswith("inc-")
    assert "complexity_score" in result
    assert 0.0 <= result["complexity_score"] <= 1.0


@pytest.mark.asyncio
async def test_supervisor_init_preserves_existing_incident_id():
    """supervisor_init_node should NOT overwrite an existing incident_id."""
    from agents.supervisor import supervisor_init_node

    alert = make_alert()
    state = make_initial_state(alert)
    state["incident_id"] = "inc-existing-001"
    result = await supervisor_init_node(state)
    assert result["incident_id"] == "inc-existing-001"


@pytest.mark.asyncio
async def test_supervisor_init_complexity_increases_with_severity():
    """Higher severity alerts should produce higher complexity scores."""
    from agents.supervisor import supervisor_init_node

    alert_p3 = make_alert(severity="P3", anomaly_score=0.0)
    state_p3 = make_initial_state(alert_p3)
    result_p3 = await supervisor_init_node(state_p3)

    alert_p1 = make_alert(severity="P1", anomaly_score=-0.9)
    state_p1 = make_initial_state(alert_p1)
    result_p1 = await supervisor_init_node(state_p1)

    assert result_p1["complexity_score"] > result_p3["complexity_score"]


@pytest.mark.asyncio
async def test_detective_node_mock_fallback():
    """Detective node returns mock findings when LLM is unavailable."""
    from agents.detective import detective_node

    with patch("agents.llm.get_llm", return_value=None):
        alert = make_alert()
        state = make_initial_state(alert)
        state["complexity_score"] = 0.5
        result = await detective_node(state)
        assert "detective_findings" in result
        findings = result["detective_findings"]
        assert "correlated_services" in findings
        assert "likely_origin" in findings
        assert "evidence" in findings
        assert "tokens_used" in findings


@pytest.mark.asyncio
async def test_supervisor_synthesize_mock_fallback_autonomous():
    """Supervisor synthesize produces autonomous result in mock mode for P1/backend/restart."""
    from agents.supervisor import supervisor_synthesize_node

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]]}
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    with (
        patch("agents.llm.get_llm", return_value=None),
        patch("chromadb.PersistentClient", return_value=mock_client),
    ):
        alert = make_alert(service="backend", severity="P1", anomaly_score=-0.89)
        state = make_initial_state(alert)
        state["incident_id"] = "inc-e2e-001"
        state["complexity_score"] = 0.5
        state["detective_findings"] = {
            "correlated_services": ["backend"],
            "likely_origin": "backend",
            "evidence": "High CPU and error rate",
        }
        state["topologist_findings"] = {
            "upstream_services": [],
            "downstream_services": ["database-stub"],
            "bottleneck": "backend",
        }
        state["historian_findings"] = {
            "recent_deploys": [],
            "suspect_commit": None,
            "deploy_time": None,
        }
        state["log_findings"] = {
            "suspect_stack_trace": "CrashLoopBackOff",
            "reasoning": "Pod was OOMKilled",
        }
        result = await supervisor_synthesize_node(state)
        assert "hypothesis" in result
        assert "confidence" in result
        assert "recommended_action" in result
        assert "requires_human_approval" in result
        # Mock fallback with P1 + restart should be autonomous
        assert result["requires_human_approval"] is False


@pytest.mark.asyncio
async def test_e2e_full_pipeline_mock_mode():
    """Full pipeline runs end-to-end in mock mode without errors."""
    from agents.supervisor import supervisor_init_node, supervisor_synthesize_node

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]]}
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    alert = make_alert(service="frontend", severity="P2", anomaly_score=-0.55)
    state = make_initial_state(alert)

    with (
        patch("agents.llm.get_llm", return_value=None),
        patch("chromadb.PersistentClient", return_value=mock_client),
    ):
        # Step 1: init
        init_result = await supervisor_init_node(state)
        state.update(init_result)
        assert state["incident_id"] is not None
        assert state["incident_id"].startswith("inc-")

        # Step 2: Add mock agent findings
        state["detective_findings"] = {
            "correlated_services": [],
            "likely_origin": "frontend",
            "evidence": "CPU saturation at 94%",
        }
        state["topologist_findings"] = {
            "upstream_services": [],
            "downstream_services": ["backend"],
            "bottleneck": "frontend",
        }
        state["historian_findings"] = {
            "recent_deploys": [],
            "suspect_commit": None,
        }
        state["log_findings"] = {
            "suspect_stack_trace": None,
            "reasoning": "Resource exhaustion",
        }

        # Step 3: synthesize
        synth_result = await supervisor_synthesize_node(state)
        state.update(synth_result)

        # Verify complete pipeline output
        assert state["hypothesis"] is not None
        assert state["confidence"] is not None
        assert state["recommended_action"] is not None
        assert isinstance(state["requires_human_approval"], bool)
        assert isinstance(state["confidence"], float)
        assert 0.0 <= state["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_e2e_pipeline_p1_produces_autonomous_action():
    """P1 alert pipeline should produce an autonomous action (no human approval)."""
    from agents.supervisor import supervisor_init_node, supervisor_synthesize_node

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "distances": [[]], "metadatas": [[]]}
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    alert = make_alert(service="backend", severity="P1", anomaly_score=-0.92)
    state = make_initial_state(alert)

    with (
        patch("agents.llm.get_llm", return_value=None),
        patch("chromadb.PersistentClient", return_value=mock_client),
    ):
        init_result = await supervisor_init_node(state)
        state.update(init_result)

        state["detective_findings"] = {
            "correlated_services": ["backend"],
            "likely_origin": "backend",
            "evidence": "Pod restarted 5 times due to pod-delete chaos",
        }
        state["topologist_findings"] = {
            "upstream_services": [],
            "downstream_services": [],
            "bottleneck": "backend",
        }
        state["historian_findings"] = {"recent_deploys": [], "suspect_commit": None}
        state["log_findings"] = {
            "suspect_stack_trace": "CrashLoopBackOff",
            "reasoning": "Pod deleted by LitmusChaos",
        }

        synth_result = await supervisor_synthesize_node(state)
        state.update(synth_result)

        # P1 with clear restart action should be autonomous
        assert state["requires_human_approval"] is False
        assert state["recommended_action"] in ["restart", "restart_pod", "scale_replicas", "none"]
