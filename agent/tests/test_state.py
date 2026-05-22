from state import Alert, AgentState

def test_alert_model():
    alert = Alert(
        id="alert-123",
        service="frontend",
        severity="P1",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8, "memory": 0.9},
        anomaly_score=-0.65
    )
    assert alert.id == "alert-123"
    assert alert.service == "frontend"
    assert alert.severity == "P1"
    assert alert.timestamp == 1716390000.0
    assert alert.metric_snapshot["cpu"] == 0.8
    assert alert.anomaly_score == -0.65

def test_agent_state_dict():
    alert = Alert(
        id="alert-123",
        service="frontend",
        severity="P1",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8, "memory": 0.9},
        anomaly_score=-0.65
    )
    state: AgentState = {
        "incident_id": "inc-456",
        "alert": alert,
        "detective_findings": {"correlated": ["backend"]},
        "topologist_findings": {"bottleneck": "backend"},
        "historian_findings": {"suspect_commit": "a1b2c3"},
        "hypothesis": "Frontend down due to backend commit",
        "confidence": 0.9,
        "recommended_action": "rollback",
        "requires_human_approval": True
    }
    assert state["incident_id"] == "inc-456"
    assert state["alert"].service == "frontend"
    assert state["detective_findings"]["correlated"] == ["backend"]
    assert state["topologist_findings"]["bottleneck"] == "backend"
    assert state["historian_findings"]["suspect_commit"] == "a1b2c3"
    assert state["hypothesis"] == "Frontend down due to backend commit"
    assert state["confidence"] == 0.9
    assert state["recommended_action"] == "rollback"
    assert state["requires_human_approval"] is True
