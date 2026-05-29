import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from remediator.server import app, actions_history, flapping_history, RemediationRequest, remediation_store
from remediator.actions import ActionResult

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_history():
    actions_history.clear()
    flapping_history.clear()
    remediation_store.clear()

def test_get_actions_empty():
    response = client.get("/actions")
    assert response.status_code == 200
    assert response.json() == []

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "actions_count" in data

def test_remediate_none_action():
    payload = {
        "incident_id": "inc-none",
        "hypothesis": "No anomaly detected, CPU usage within bounds",
        "confidence": 0.95,
        "recommended_action": "none",
        "requires_human_approval": False,
        "reasoning": "Golden signals look normal"
    }
    response = client.post("/remediate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Escalated: No automated remediation executed" in data["action_taken"]
    
    # Check history contains action
    assert len(actions_history) == 1
    assert actions_history[0].success is True

def test_remediate_restart_p1_no_approval_with_alert_verification():
    payload = {
        "incident_id": "inc-restart",
        "hypothesis": "CrashLoopBackOff on service 'backend'",
        "confidence": 0.85,
        "recommended_action": "restart",
        "requires_human_approval": False,
        "reasoning": "backend service is failing liveness probes",
        "alert": {
            "id": "alert-123",
            "service": "backend",
            "severity": "P1",
            "timestamp": 1234567.8,
            "metric_snapshot": {"cpu": 1.0},
            "anomaly_score": -0.8
        }
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Successfully restarted backend pod",
        duration_seconds=1.2
    )

    # Mock K8s listing to resolve pod name, and verifier check
    mock_k8s_v1 = MagicMock()
    mock_pod = MagicMock()
    mock_pod.metadata.name = "backend-real-pod"
    mock_k8s_v1.list_namespaced_pod.return_value.items = [mock_pod]

    with patch("remediator.server.restart_pod", return_value=mock_action_result) as mock_restart, \
         patch("remediator.server.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_k8s_v1), \
         patch("remediator.server.verify_resolution", return_value=True) as mock_verify:
        
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["action_taken"] == "Successfully restarted backend pod"
        mock_restart.assert_called_with(namespace="neuroops-demo", pod_name="backend-real-pod")
        assert mock_verify.called

def test_remediate_restart_p1_no_pods_fallback():
    payload = {
        "incident_id": "inc-restart-fallback",
        "hypothesis": "CrashLoopBackOff on service 'frontend'",
        "confidence": 0.85,
        "recommended_action": "restart",
        "requires_human_approval": False,
        "reasoning": "frontend service is crashing"
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Successfully restarted frontend pod",
        duration_seconds=1.2
    )

    # Mock K8s list returns empty list
    mock_k8s_v1 = MagicMock()
    mock_k8s_v1.list_namespaced_pod.return_value.items = []

    with patch("remediator.server.restart_pod", return_value=mock_action_result) as mock_restart, \
         patch("remediator.server.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_k8s_v1):
        
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        mock_restart.assert_called_with(namespace="neuroops-demo", pod_name="frontend-pod-fallback")

def test_remediate_restart_p1_k8s_not_configured_fallback():
    payload = {
        "incident_id": "inc-restart-mock",
        "hypothesis": "CrashLoopBackOff on service 'database-stub'",
        "confidence": 0.85,
        "recommended_action": "restart",
        "requires_human_approval": False,
        "reasoning": "database-stub service is crashing"
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Mock restarted pod",
        duration_seconds=0.5
    )

    with patch("remediator.server.restart_pod", return_value=mock_action_result) as mock_restart, \
         patch("remediator.server.k8s_configured", False):
        
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        mock_restart.assert_called_with(namespace="neuroops-demo", pod_name="database-stub-pod-mock")

def test_remediate_restart_p1_pod_list_exception():
    payload = {
        "incident_id": "inc-restart-exc",
        "hypothesis": "CrashLoopBackOff on service 'backend'",
        "confidence": 0.85,
        "recommended_action": "restart",
        "requires_human_approval": False,
        "reasoning": "backend is crashing"
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Successfully restarted backend pod",
        duration_seconds=1.2
    )

    # Mock K8s list raises exception
    mock_k8s_v1 = MagicMock()
    mock_k8s_v1.list_namespaced_pod.side_effect = Exception("Forbidden")

    with patch("remediator.server.restart_pod", return_value=mock_action_result) as mock_restart, \
         patch("remediator.server.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_k8s_v1):
        
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        mock_restart.assert_called_with(namespace="neuroops-demo", pod_name="backend-pod-fallback")

def test_remediate_p2_human_approval_rejected():
    payload = {
        "incident_id": "inc-rollback-reject",
        "hypothesis": "Deploy failure on backend",
        "confidence": 0.89,
        "recommended_action": "rollback",
        "requires_human_approval": True,
        "reasoning": "Suspect deployment found"
    }
    
    # Mock human rejection
    with patch("remediator.server.prompt_human", return_value=False) as mock_prompt:
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Rejected: Action 'rollback' rejected" in data["action_taken"]
        assert mock_prompt.called

def test_remediate_p2_human_approval_approved():
    payload = {
        "incident_id": "inc-rollback-approve",
        "hypothesis": "Deploy failure on backend",
        "confidence": 0.89,
        "recommended_action": "rollback",
        "requires_human_approval": True,
        "reasoning": "Suspect deployment found",
        "deployment_name": "backend-deploy"
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Rolled back deployment",
        duration_seconds=3.5
    )

    with patch("remediator.server.prompt_human", return_value=True) as mock_prompt, \
         patch("remediator.server.rollback_deployment", return_value=mock_action_result) as mock_rollback:
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["action_taken"] == "Rolled back deployment"
        assert mock_prompt.called
        mock_rollback.assert_called_with(namespace="neuroops-demo", deployment_name="backend-deploy")

def test_remediate_p2_auto_approve_skips_prompt():
    payload = {
        "incident_id": "inc-rollback-auto-approve",
        "hypothesis": "Deploy failure on backend",
        "confidence": 0.89,
        "recommended_action": "rollback",
        "requires_human_approval": True,
        "reasoning": "Suspect deployment found",
        "deployment_name": "backend-deploy",
        "auto_approve": True
    }

    mock_action_result = ActionResult(
        success=True,
        action_taken="Rolled back deployment",
        duration_seconds=3.5
    )

    with patch("remediator.server.prompt_human") as mock_prompt, \
         patch("remediator.server.rollback_deployment", return_value=mock_action_result) as mock_rollback:
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert mock_prompt.called is False
        mock_rollback.assert_called_with(namespace="neuroops-demo", deployment_name="backend-deploy")

def test_remediate_scale_deployment():
    payload = {
        "incident_id": "inc-scale",
        "hypothesis": "High CPU load on backend",
        "confidence": 0.85,
        "recommended_action": "scale",
        "requires_human_approval": False,
        "reasoning": "backend CPU usage > 90%",
        "replicas": 5
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Scaled replicas to 5",
        duration_seconds=1.5
    )

    with patch("remediator.server.scale_deployment", return_value=mock_action_result) as mock_scale:
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["action_taken"] == "Scaled replicas to 5"
        mock_scale.assert_called_with(namespace="neuroops-demo", deployment_name="backend", replicas=5)

def test_remediate_patch_configmap():
    payload = {
        "incident_id": "inc-patch",
        "hypothesis": "Log level is DEBUG, causing IO bottlenecks on backend",
        "confidence": 0.75,
        "recommended_action": "patch_configmap",
        "requires_human_approval": False,
        "reasoning": "Set log level to INFO",
        "patch": {"data": {"LOG_LEVEL": "INFO"}}
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Patched ConfigMap",
        duration_seconds=0.6
    )

    with patch("remediator.server.patch_configmap", return_value=mock_action_result) as mock_patch:
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_patch.assert_called_with(namespace="neuroops-demo", name="backend-config", patch={"data": {"LOG_LEVEL": "INFO"}})

def test_remediate_open_pr():
    payload = {
        "incident_id": "inc-open-pr",
        "hypothesis": "Deploy code fix recommended",
        "confidence": 0.70,
        "recommended_action": "open_github_pr",
        "requires_human_approval": False,
        "reasoning": "Generate PR fix"
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Opened PR #45",
        duration_seconds=1.0
    )

    with patch("remediator.server.open_pr", return_value=mock_action_result) as mock_open_pr:
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_open_pr.assert_called_with(
            repo="neuroops-project/neuroops",
            title="remediation: config patch for backend incident",
            body="Generate PR fix",
            branch="remediation-inc-open-pr",
            files={"cluster/apps/manifests.yaml": "# Auto-remediation patch\n# Incident: inc-open-pr\n"}
        )

def test_remediate_verification_fail_warning():
    payload = {
        "incident_id": "inc-restart-verify-fail",
        "hypothesis": "OOMKill backend",
        "confidence": 0.85,
        "recommended_action": "restart",
        "requires_human_approval": False,
        "reasoning": "OOM detected",
        "alert": {
            "id": "alert-789",
            "service": "backend",
            "severity": "P1",
            "timestamp": 1234567.8,
            "metric_snapshot": {"memory": 1.0},
            "anomaly_score": -0.8
        }
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Successfully restarted backend pod",
        duration_seconds=1.2
    )

    with patch("remediator.server.restart_pod", return_value=mock_action_result), \
         patch("remediator.server.verify_resolution", return_value=False) as mock_verify:
        
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "warning: incident verification failed" in data["action_taken"].lower()
        assert mock_verify.called

def test_remediate_flapping_lockout():
    from remediator.server import flapping_history
    flapping_history.clear()
    
    payload = {
        "incident_id": "inc-flap-test",
        "hypothesis": "High CPU load on backend",
        "confidence": 0.85,
        "recommended_action": "scale",
        "requires_human_approval": False,
        "reasoning": "backend CPU usage > 90%",
        "replicas": 5
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Scaled replicas to 5",
        duration_seconds=1.5
    )

    with patch("remediator.server.scale_deployment", return_value=mock_action_result):
        # First action: Success
        res1 = client.post("/remediate", json=payload)
        assert res1.status_code == 200
        assert res1.json()["success"] is True
        
        # Second action: Success
        res2 = client.post("/remediate", json=payload)
        assert res2.status_code == 200
        assert res2.json()["success"] is True
        
        # Third action within 10m window: Should trigger Flapping Lockout (False)
        res3 = client.post("/remediate", json=payload)
        assert res3.status_code == 200
        data = res3.json()
        assert data["success"] is False
        assert "Flapping Lockout Active" in data["action_taken"]

def test_remediate_postmortem_generation(tmp_path):
    from remediator.server import flapping_history
    flapping_history.clear()
    
    payload = {
        "incident_id": "inc-postmortem-test",
        "hypothesis": "High CPU load on backend",
        "confidence": 0.85,
        "recommended_action": "scale",
        "requires_human_approval": False,
        "reasoning": "backend CPU usage > 90%",
        "replicas": 5
    }
    
    mock_action_result = ActionResult(
        success=True,
        action_taken="Scaled replicas to 5",
        duration_seconds=1.5
    )

    with patch("remediator.server.scale_deployment", return_value=mock_action_result), \
         patch("remediator.postmortem.os.makedirs") as mock_makedirs, \
         patch("builtins.open", create=True) as mock_open:
        
        response = client.post("/remediate", json=payload)
        assert response.status_code == 200
        assert mock_makedirs.called
        assert mock_open.called
