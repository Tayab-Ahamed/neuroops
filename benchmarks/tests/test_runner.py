from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from benchmarks.runner import (
    execute_run,
    main,
    render_scenario_summary,
    verify_k8s_reachable,
    verify_service_reachable,
)


@pytest.fixture(autouse=True)
def mock_sleep():
    """Bypasses time.sleep to run tests instantly."""
    with patch("time.sleep", return_value=None):
        yield


# 1. Helper function tests
def test_verify_k8s_reachable_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert verify_k8s_reachable() is True


def test_verify_k8s_reachable_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert verify_k8s_reachable() is False


def test_verify_k8s_reachable_exception():
    with patch("subprocess.run", side_effect=Exception("binary not found")):
        assert verify_k8s_reachable() is False


def test_verify_service_reachable_success():
    mock_response = MagicMock(status_code=200)
    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    with patch("httpx.Client") as mock_client_class:
        mock_client_class.return_value.__enter__.return_value = mock_client
        assert verify_service_reachable("http://test-url") is True


def test_verify_service_reachable_failure():
    mock_response = MagicMock(status_code=500)
    mock_client = MagicMock()
    mock_client.get.return_value = mock_response
    with patch("httpx.Client") as mock_client_class:
        mock_client_class.return_value.__enter__.return_value = mock_client
        assert verify_service_reachable("http://test-url") is False


def test_verify_service_reachable_exception():
    with patch("httpx.Client", side_effect=Exception("Connection failed")):
        assert verify_service_reachable("http://test-url") is False


# 2. execute_run scenario testing (Successful Mock run)
def test_execute_run_mock_success():
    res = execute_run("pod-delete", "backend", 1, True, "http://det", "http://agent", "http://rem")
    assert res["status"] == "success"
    assert res["scenario"] == "pod-delete"
    assert res["detection_latency"] == 15.0
    assert res["confidence"] == 0.85
    assert res["autonomous"] is True


# 3. execute_run scenario testing (Failed Mock runs / escalations)
def test_execute_run_mock_p2_escalation():
    # cpu-hog forces P2 simulation
    res = execute_run("cpu-hog", "frontend", 1, True, "http://det", "http://agent", "http://rem")
    assert res["status"] == "success"
    assert res["scenario"] == "cpu-hog"
    assert res["confidence"] == 0.55
    assert res["autonomous"] is False


# 4. execute_run scenario testing (Live runs - success)
def test_execute_run_live_success():
    mock_client = MagicMock()

    # 1st call (alerts polling): active alert returned
    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [
        {"service": "backend", "id": "alert-123", "severity": "P1"}
    ]

    # 2nd call (RCA investigate): hypothesis returned
    mock_rca_resp = MagicMock(status_code=200)
    mock_rca_resp.json.return_value = {
        "hypothesis": "CrashLoopBackOff on backend",
        "confidence": 0.85,
        "requires_human_approval": False,
    }

    # 3rd call (Remediation execute): action completed
    mock_rem_resp = MagicMock(status_code=200)
    mock_rem_resp.json.return_value = {
        "success": True,
        "action_taken": "Successfully restarted backend pod",
        "duration_seconds": 1.5,
    }

    # 4th call (resolution check): returns empty alert list
    mock_resolution_resp = MagicMock(status_code=200)
    mock_resolution_resp.json.return_value = []

    # Map responses chronologically
    mock_client.get.side_effect = [mock_alert_resp, mock_resolution_resp]
    mock_client.post.side_effect = [mock_rca_resp, mock_rem_resp]

    with patch("subprocess.run") as mock_sub, patch("httpx.Client") as mock_client_class:

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "success"
        assert res["tokens_used"] == 5000
        assert res["remediator_success"] is True
        assert res["action_taken"] == "Successfully restarted backend pod"


# 5. execute_run scenario testing (Live runs - failed chaos injection)
def test_execute_run_live_chaos_injection_fails():
    with patch("subprocess.run", side_effect=Exception("kubectl error")):
        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "failed"
        assert "Chaos Injection Failure" in res["error_message"]


# 6. execute_run scenario testing (Live runs - detector polling timeouts/errors)
def test_execute_run_live_detection_timeout():
    mock_client = MagicMock()
    # Mock connection failure or empty list inside polling loop
    mock_client.get.side_effect = Exception("Service unavailable")

    with (
        patch("subprocess.run") as mock_sub,
        patch("httpx.Client") as mock_client_class,
        patch("time.time") as mock_time,
    ):

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client
        # Cause time loop to exceed 600s instantly
        mock_time.side_effect = [100.0, 100.0, 800.0]

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "failed"
        assert "Detection Timeout" in res["error_message"]


# 7. execute_run scenario testing (Live runs - RCA failures)
def test_execute_run_live_rca_api_error():
    mock_client = MagicMock()

    # 1. Alert found
    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [{"service": "backend", "id": "alert-123"}]
    mock_client.get.return_value = mock_alert_resp

    # 2. RCA Investigate non-200
    mock_rca_resp = MagicMock(status_code=500)
    mock_client.post.return_value = mock_rca_resp

    with patch("subprocess.run") as mock_sub, patch("httpx.Client") as mock_client_class:

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "failed"
        assert "Agent API Failed" in res["error_message"]


def test_execute_run_live_rca_exception():
    mock_client = MagicMock()

    # 1. Alert found
    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [{"service": "backend", "id": "alert-123"}]
    mock_client.get.return_value = mock_alert_resp

    # 2. RCA Investigate exception
    mock_client.post.side_effect = Exception("network cut")

    with patch("subprocess.run") as mock_sub, patch("httpx.Client") as mock_client_class:

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "failed"
        assert "Agent Connection Error" in res["error_message"]


# 8. execute_run scenario testing (Live runs - Remediator failures)
def test_execute_run_live_remediator_api_error():
    mock_client = MagicMock()

    # 1. Alert found
    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [{"service": "backend", "id": "alert-123"}]
    mock_client.get.return_value = mock_alert_resp

    # 2. RCA Success
    mock_rca_resp = MagicMock(status_code=200)
    mock_rca_resp.json.return_value = {
        "hypothesis": "Crash",
        "confidence": 0.9,
        "requires_human_approval": False,
    }

    # 3. Remediate non-200
    mock_rem_resp = MagicMock(status_code=500)

    mock_client.post.side_effect = [mock_rca_resp, mock_rem_resp]

    with patch("subprocess.run") as mock_sub, patch("httpx.Client") as mock_client_class:

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "failed"
        assert "Remediator API Failed" in res["error_message"]


def test_execute_run_live_remediator_exception():
    mock_client = MagicMock()

    # 1. Alert found
    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [{"service": "backend", "id": "alert-123"}]
    mock_client.get.return_value = mock_alert_resp

    # 2. RCA Success
    mock_rca_resp = MagicMock(status_code=200)
    mock_rca_resp.json.return_value = {
        "hypothesis": "Crash",
        "confidence": 0.9,
        "requires_human_approval": False,
    }

    # 3. Remediate exception
    mock_client.post.side_effect = [mock_rca_resp, Exception("remediator dead")]

    with patch("subprocess.run") as mock_sub, patch("httpx.Client") as mock_client_class:

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "failed"
        assert "Remediator Connection Error" in res["error_message"]


# 9. execute_run scenario testing (Live runs - verification timeouts/errors)
def test_execute_run_live_resolution_timeout():
    mock_client = MagicMock()

    # 1. Alert found
    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [{"service": "backend", "id": "alert-123"}]

    # 2. RCA Success
    mock_rca_resp = MagicMock(status_code=200)
    mock_rca_resp.json.return_value = {
        "hypothesis": "Crash",
        "confidence": 0.9,
        "requires_human_approval": False,
    }

    # 3. Remediate Success
    mock_rem_resp = MagicMock(status_code=200)
    mock_rem_resp.json.return_value = {
        "success": True,
        "action_taken": "fixed",
        "duration_seconds": 1.0,
    }

    mock_client.get.return_value = mock_alert_resp
    mock_client.post.side_effect = [mock_rca_resp, mock_rem_resp]

    with (
        patch("subprocess.run") as mock_sub,
        patch("httpx.Client") as mock_client_class,
        patch("time.time") as mock_time,
    ):

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client

        # Return 100.0 for the first 20 calls (detection + remediation phases),
        # then 800.0 to trigger the resolution-verification timeout (>600s).
        # 7 was too few — the runner makes more time.time() calls during
        # chaos injection, polling and remediation before reaching the verifier.
        time_calls = []

        def mock_time_fn():
            time_calls.append(True)
            if len(time_calls) <= 20:
                return 100.0
            return 800.0

        mock_time.side_effect = mock_time_fn

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "failed"
        assert "Resolution Verification Timeout" in res["error_message"]


# 10. Helper render tests
def test_render_scenario_summary_failed_runs():
    runs = [
        {
            "run": 1,
            "status": "failed",
            "detection_latency": 600.0,
            "diagnosis_latency": 600.0,
            "remediation_latency": 600.0,
            "total_mttr": 600.0,
            "tokens_used": 0,
            "confidence": 0.0,
            "autonomous": False,
            "error_message": "Timeout",
        }
    ]
    # Verify execution does not crash
    render_scenario_summary("pod-delete", runs)


# 11. CLI Execution Paths
def test_cli_mock_runs():
    runner = CliRunner()
    # Mock report compiler to avoid file IO dependencies during tests
    with (
        patch("benchmarks.runner.verify_k8s_reachable", return_value=False),
        patch("benchmarks.runner.verify_service_reachable", return_value=False),
        patch("benchmarks.report.compile_report") as mock_report,
    ):

        result = runner.invoke(main, ["--scenario", "pod-delete", "--runs", "1", "--mock"])
        assert result.exit_code == 0
        assert "NeuroOps Chaos Engineering Benchmark Suite" in result.output
        assert "Average Agent MTTR" in result.output
        assert mock_report.called


def test_cli_live_runs_fallback_to_mock():
    runner = CliRunner()
    # Mocking K8s and microservices to be offline to force auto-detection mock trigger
    with (
        patch("benchmarks.runner.verify_k8s_reachable", return_value=False),
        patch("benchmarks.runner.verify_service_reachable", return_value=False),
        patch("benchmarks.report.compile_report") as mock_report,
    ):

        result = runner.invoke(main, ["--scenario", "pod-delete", "--runs", "1"])
        assert result.exit_code == 0
        assert "WARN: Local stack or Kubernetes is not fully available." in result.output
        assert mock_report.called


def test_cli_unknown_scenario():
    runner = CliRunner()
    result = runner.invoke(main, ["--scenario", "unknown-scenario"])
    assert result.exit_code == 0
    assert "unknown-scenario" in result.output
    assert "Unknown scenario" in result.output


def test_cli_live_runs_all_online():
    runner = CliRunner()
    with (
        patch("benchmarks.runner.verify_k8s_reachable", return_value=True),
        patch("benchmarks.runner.verify_service_reachable", return_value=True),
        patch("benchmarks.runner.execute_run") as mock_execute,
        patch("benchmarks.report.compile_report") as mock_report,
    ):

        mock_execute.return_value = {
            "scenario": "pod-delete",
            "run": 1,
            "status": "success",
            "detection_latency": 10.0,
            "diagnosis_latency": 5.0,
            "remediation_latency": 15.0,
            "total_mttr": 30.0,
            "tokens_used": 100,
            "confidence": 0.9,
            "autonomous": True,
            "action_taken": "restart",
            "remediator_success": True,
            "error_message": "",
        }

        result = runner.invoke(main, ["--scenario", "pod-delete", "--runs", "1"])
        assert result.exit_code == 0
        assert "Executing LIVE chaos." in result.output
        assert mock_report.called


def test_cli_report_compilation_exception():
    runner = CliRunner()
    with (
        patch("benchmarks.runner.verify_k8s_reachable", return_value=False),
        patch("benchmarks.runner.verify_service_reachable", return_value=False),
        patch(
            "benchmarks.report.compile_report", side_effect=Exception("Disk full")
        ),
        patch("benchmarks.runner.logger") as mock_logger,
    ):

        result = runner.invoke(main, ["--scenario", "pod-delete", "--runs", "1", "--mock"])
        assert result.exit_code == 0
        assert mock_logger.error.called


def test_execute_run_live_detection_exception_retry():
    mock_client = MagicMock()

    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [
        {"service": "backend", "id": "alert-123", "severity": "P1"}
    ]

    mock_rca_resp = MagicMock(status_code=200)
    mock_rca_resp.json.return_value = {
        "hypothesis": "Crash",
        "confidence": 0.85,
        "requires_human_approval": False,
    }

    mock_rem_resp = MagicMock(status_code=200)
    mock_rem_resp.json.return_value = {
        "success": True,
        "action_taken": "restart",
        "duration_seconds": 1.0,
    }

    mock_resolution_resp = MagicMock(status_code=200)
    mock_resolution_resp.json.return_value = []

    mock_client.get.side_effect = [
        Exception("Temporary glitch"),
        mock_alert_resp,
        mock_resolution_resp,
    ]
    mock_client.post.side_effect = [mock_rca_resp, mock_rem_resp]

    with patch("subprocess.run") as mock_sub, patch("httpx.Client") as mock_client_class:

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "success"


def test_execute_run_live_cleanup_exception():
    mock_client = MagicMock()

    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [
        {"service": "backend", "id": "alert-123", "severity": "P1"}
    ]

    mock_rca_resp = MagicMock(status_code=200)
    mock_rca_resp.json.return_value = {
        "hypothesis": "Crash",
        "confidence": 0.85,
        "requires_human_approval": False,
    }

    mock_rem_resp = MagicMock(status_code=200)
    mock_rem_resp.json.return_value = {
        "success": True,
        "action_taken": "restart",
        "duration_seconds": 1.0,
    }

    mock_resolution_resp = MagicMock(status_code=200)
    mock_resolution_resp.json.return_value = []

    mock_client.get.side_effect = [mock_alert_resp, mock_resolution_resp]
    mock_client.post.side_effect = [mock_rca_resp, mock_rem_resp]

    with (
        patch("subprocess.run") as mock_sub,
        patch("httpx.Client") as mock_client_class,
        patch("benchmarks.runner.logger") as mock_logger,
    ):

        mock_sub.side_effect = [MagicMock(returncode=0), Exception("kubectl delete failed")]
        mock_client_class.return_value.__enter__.return_value = mock_client

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "success"
        assert any(
            "Cleanup during resolution polling failed" in call[0][0]
            for call in mock_logger.warning.call_args_list
        )


def test_execute_run_live_verifier_exception_retry():
    mock_client = MagicMock()

    mock_alert_resp = MagicMock(status_code=200)
    mock_alert_resp.json.return_value = [
        {"service": "backend", "id": "alert-123", "severity": "P1"}
    ]

    mock_rca_resp = MagicMock(status_code=200)
    mock_rca_resp.json.return_value = {
        "hypothesis": "Crash",
        "confidence": 0.85,
        "requires_human_approval": False,
    }

    mock_rem_resp = MagicMock(status_code=200)
    mock_rem_resp.json.return_value = {
        "success": True,
        "action_taken": "restart",
        "duration_seconds": 1.0,
    }

    mock_resolution_resp = MagicMock(status_code=200)
    mock_resolution_resp.json.return_value = []

    mock_client.get.side_effect = [
        mock_alert_resp,
        Exception("Temp verifier glitch"),
        mock_resolution_resp,
    ]
    mock_client.post.side_effect = [mock_rca_resp, mock_rem_resp]

    with patch("subprocess.run") as mock_sub, patch("httpx.Client") as mock_client_class:

        mock_sub.return_value = MagicMock(returncode=0)
        mock_client_class.return_value.__enter__.return_value = mock_client

        res = execute_run(
            "pod-delete", "backend", 1, False, "http://det", "http://agent", "http://rem"
        )
        assert res["status"] == "success"


import runpy


def test_runner_main_execution():
    with patch(
        "sys.argv", ["benchmarks/runner.py", "--scenario", "pod-delete", "--runs", "1", "--mock"]
    ):
        with patch("benchmarks.report.compile_report") as mock_compile:
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_path("benchmarks/runner.py", run_name="__main__")
            assert exc_info.value.code == 0
            assert mock_compile.called
