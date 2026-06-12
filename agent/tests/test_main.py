from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_investigate_endpoint_success():
    alert_payload = {
        "id": "alert-abc",
        "service": "backend",
        "severity": "P1",
        "timestamp": 1716390000.0,
        "metric_snapshot": {"cpu_utilization": 98.4},
        "anomaly_score": -0.72,
    }

    # Send request to investigate
    response = client.post("/investigate", json=alert_payload)
    assert response.status_code == 200

    data = response.json()
    assert "incident_id" in data
    assert data["hypothesis"] is not None
    assert data["confidence"] is not None
    assert data["recommended_action"] is not None

    incident_id = data["incident_id"]

    # Retrieve reasoning trace timeline
    trace_response = client.get(f"/incidents/{incident_id}/trace")
    assert trace_response.status_code == 200

    trace_data = trace_response.json()
    assert len(trace_data) == 6
    assert trace_data[0]["agent"] == "supervisor_init"
    assert trace_data[1]["agent"] == "detective"
    assert trace_data[2]["agent"] == "topologist"
    assert trace_data[3]["agent"] == "historian"
    assert trace_data[4]["agent"] == "log_analyser"
    assert trace_data[5]["agent"] == "supervisor_synthesize"

    # Retrieve single incident detail
    detail_response = client.get(f"/incidents/{incident_id}")
    assert detail_response.status_code == 200
    detail_data = detail_response.json()
    assert detail_data["incident_id"] == incident_id
    assert detail_data["service"] == "backend"
    assert "trace" in detail_data
    assert "metric_snapshot" in detail_data


def test_get_incident_endpoint_not_found():
    response = client.get("/incidents/inc-missing")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_get_trace_endpoint_not_found():

    response = client.get("/incidents/inc-missing/trace")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "persisted_incidents" in data


@patch("main.graph.ainvoke", new_callable=AsyncMock)
def test_investigate_endpoint_error(mock_ainvoke):
    mock_ainvoke.side_effect = Exception("LangGraph fatal error")

    alert_payload = {
        "id": "alert-abc",
        "service": "backend",
        "severity": "P1",
        "timestamp": 1716390000.0,
        "metric_snapshot": {"cpu_utilization": 98.4},
        "anomaly_score": -0.72,
    }

    response = client.post("/investigate", json=alert_payload)
    assert response.status_code == 500
    assert "LangGraph fatal error" in response.json()["detail"]


def test_analytics_endpoints():
    from main import incident_store

    # Test empty or baseline state
    response_mttr = client.get("/analytics/mttr")
    assert response_mttr.status_code == 200

    response_cost = client.get("/analytics/cost")
    assert response_cost.status_code == 200

    response_res = client.get("/analytics/resolution")
    assert response_res.status_code == 200

    # Save a mock incident
    incident_store.save_incident(
        incident_id="inc-pod-delete-123",
        service="backend",
        alert_id="alert-1",
        hypothesis="Pod delete error injected",
        confidence=0.85,
        recommended_action="Restart pod",
        requires_human_approval=False,
        reasoning="Test reasoning",
        tokens_used=1500,
        remediation_result={"success": True},
        trace_timeline=[],
        alert_timestamp=1716390000.0,
        resolved_at=1716390100.0,
        mttr_seconds=100.0,
        metric_snapshot={"cpu_utilization": 50.0},
        model_used="claude-haiku-4-5-20251001",
    )

    incident_store.save_incident(
        incident_id="inc-cpu-hog-456",
        service="frontend",
        alert_id="alert-2",
        hypothesis="CPU hog error",
        confidence=0.9,
        recommended_action="Scale down pod",
        requires_human_approval=True,
        reasoning="Test reasoning 2",
        tokens_used=3000,
        remediation_result={"success": True},
        trace_timeline=[],
        alert_timestamp=1716390000.0,
        resolved_at=1716390200.0,
        mttr_seconds=200.0,
        metric_snapshot={"cpu_utilization": 90.0},
        model_used="claude-sonnet-4-6",
    )

    # Test mttr endpoint with data
    response_mttr = client.get("/analytics/mttr")
    assert response_mttr.status_code == 200
    mttr_data = response_mttr.json()
    assert mttr_data["total_incidents"] >= 2
    assert any(x["scenario"] == "pod-delete" for x in mttr_data["per_scenario"])
    assert any(x["scenario"] == "cpu-hog" for x in mttr_data["per_scenario"])

    # Test cost endpoint with data
    response_cost = client.get("/analytics/cost")
    assert response_cost.status_code == 200
    cost_data = response_cost.json()
    assert cost_data["total_tokens"] >= 4500
    assert "model_breakdown" in cost_data
    assert cost_data["model_breakdown"]["haiku"]["calls"] >= 1
    assert cost_data["model_breakdown"]["sonnet"]["calls"] >= 1

    # Test resolution endpoint with data
    response_res = client.get("/analytics/resolution")
    assert response_res.status_code == 200
    res_data = response_res.json()
    assert "daily" in res_data
    assert len(res_data["daily"]) == 7
