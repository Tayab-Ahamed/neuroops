from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from remediator.actions import ActionResult
from remediator.server import app, is_known_action, limiter


@pytest.fixture(autouse=True)
def isolated_rate_limit_state():
    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.parametrize("action", [
    "do_not_restart", "restart_pod_then_rollback", "autoscale", "please_open_pr",
])
def test_substring_matches_cannot_execute_remediation(action):
    payload = {
        "incident_id": "invalid-action", "hypothesis": "backend unhealthy",
        "confidence": 0.9, "recommended_action": action,
        "requires_human_approval": False, "reasoning": "test",
    }
    with patch("remediator.server._remediate_impl", new_callable=AsyncMock) as execute:
        execute.return_value = ActionResult(success=True, action_taken="unexpected", duration_seconds=0)
        response = TestClient(app).post("/remediate", json=payload)
    assert response.status_code == 422
    execute.assert_not_called()


@pytest.mark.parametrize("action", [
    "restart", "restart_pod", "rollback", "rollback_deployment", "scale",
    "scale_replicas", "patch_configmap", "open_pr", "open_github_pr", "none",
])
def test_documented_action_aliases_remain_available(action):
    assert is_known_action(action)


@pytest.mark.parametrize("action", ["do_not_restart", "restart_pod_then_rollback", "autoscale", "please_open_pr"])
def test_allowlist_rejects_substrings(action):
    assert not is_known_action(action)


@pytest.mark.parametrize("action", ["restart_pod", " SCALE_REPLICAS "])
def test_valid_action_request_reaches_dispatch(action):
    payload = {
        "incident_id": "valid-action", "hypothesis": "backend unhealthy",
        "confidence": 0.9, "recommended_action": action,
        "requires_human_approval": False, "reasoning": "test",
    }
    with patch("remediator.server._remediate_impl", new_callable=AsyncMock) as execute:
        execute.return_value = ActionResult(success=True, action_taken="planned", duration_seconds=0)
        response = TestClient(app).post("/remediate", json=payload)
    assert response.status_code == 200
    execute.assert_awaited_once()
