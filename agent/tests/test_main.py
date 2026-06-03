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
