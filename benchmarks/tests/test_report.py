import os
import json
import pytest
from unittest.mock import patch
from benchmarks.report import generate_ascii_bar, compile_report

# 1. Test generate_ascii_bar
def test_generate_ascii_bar_normal():
    bar = generate_ascii_bar(10, 20, width=10)
    assert bar == "█████░░░░░"

def test_generate_ascii_bar_zero_max():
    bar = generate_ascii_bar(10, 0, width=10)
    assert bar == "░" * 10

def test_generate_ascii_bar_negative_max():
    bar = generate_ascii_bar(10, -5, width=10)
    assert bar == "░" * 10


# 2. Test compile_report (Exceptions and edge cases)
def test_compile_report_file_not_found():
    # Verify it handles missing file gracefully without crashing
    with patch("benchmarks.report.logger") as mock_logger:
        compile_report("benchmarks/non_existent.json")
        assert mock_logger.error.called


def test_compile_report_empty_list(tmp_path):
    temp_json = tmp_path / "empty_results.json"
    with open(temp_json, "w") as f:
        json.dump([], f)
        
    with patch("benchmarks.report.logger") as mock_logger:
        compile_report(str(temp_json))
        assert mock_logger.warning.called


# 3. Test compile_report (Successful generation and formatting verification)
def test_compile_report_success(tmp_path):
    results = [
        {
            "scenario": "pod-delete",
            "run": 1,
            "status": "success",
            "detection_latency": 15.0,
            "diagnosis_latency": 5.0,
            "remediation_latency": 20.0,
            "total_mttr": 40.0,
            "tokens_used": 4000,
            "confidence": 0.85,
            "autonomous": True,
            "action_taken": "Restarted",
            "remediator_success": True,
            "error_message": ""
        },
        {
            "scenario": "pod-delete",
            "run": 2,
            "status": "success",
            "detection_latency": 17.0,
            "diagnosis_latency": 6.0,
            "remediation_latency": 22.0,
            "total_mttr": 45.0,
            "tokens_used": 4200,
            "confidence": 0.82,
            "autonomous": True,
            "action_taken": "Restarted",
            "remediator_success": True,
            "error_message": ""
        },
        {
            "scenario": "cpu-hog",
            "run": 1,
            "status": "success",
            "detection_latency": 30.0,
            "diagnosis_latency": 10.0,
            "remediation_latency": 40.0,
            "total_mttr": 80.0,
            "tokens_used": 5000,
            "confidence": 0.55,
            "autonomous": False,
            "action_taken": "Scaled up",
            "remediator_success": True,
            "error_message": ""
        },
        {
            "scenario": "disk-fill",
            "run": 1,
            "status": "success",
            "detection_latency": 40.0,
            "diagnosis_latency": 15.0,
            "remediation_latency": 45.0,
            "total_mttr": 100.0,
            "tokens_used": 6000,
            "confidence": 0.50,
            "autonomous": False,
            "action_taken": "Cleaned up",
            "remediator_success": True,
            "error_message": ""
        }
    ]

    results_file = tmp_path / "results.json"
    report_file = tmp_path / "REPORT.md"

    with open(results_file, "w") as f:
        json.dump(results, f)

    compile_report(str(results_file), str(report_file))

    # Assert report file exists and contains correct content elements
    assert os.path.exists(report_file)
    with open(report_file, "r", encoding="utf-8") as f:
        content = f.read()
        
    assert "# NeuroOps Automated Recovery Benchmark Report" in content
    assert "Executive Summary" in content
    assert "Overall MTTR Improvement" in content
    assert "MTTR Reduction Visualized" in content
    assert "LLM Token Cost & Efficiency Tracker" in content
    assert "pod-delete" in content
    assert "cpu-hog" in content
    assert "Autonomous" in content
    assert "Escalated (Human-in-loop)" in content


def test_compile_report_mixed_success_and_failed_scenarios(tmp_path):
    results = [
        {
            "scenario": "pod-delete",
            "run": 1,
            "status": "failed",
            "detection_latency": 600.0,
            "diagnosis_latency": 600.0,
            "remediation_latency": 600.0,
            "total_mttr": 600.0,
            "tokens_used": 0,
            "confidence": 0.0,
            "autonomous": False,
            "action_taken": "none",
            "remediator_success": False,
            "error_message": "Timeout"
        },
        {
            "scenario": "cpu-hog",
            "run": 1,
            "status": "success",
            "detection_latency": 30.0,
            "diagnosis_latency": 10.0,
            "remediation_latency": 40.0,
            "total_mttr": 80.0,
            "tokens_used": 5000,
            "confidence": 0.55,
            "autonomous": False,
            "action_taken": "Scaled up",
            "remediator_success": True,
            "error_message": ""
        }
    ]
    results_file = tmp_path / "results_mixed.json"
    report_file = tmp_path / "REPORT_mixed.md"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f)
    
    compile_report(str(results_file), str(report_file))
    assert os.path.exists(report_file)


import runpy
def test_report_main_execution(tmp_path):
    temp_json = tmp_path / "results_main.json"
    with open(temp_json, "w", encoding="utf-8") as f:
        json.dump([], f)
    
    with patch("sys.argv", ["benchmarks/report.py", str(temp_json)]):
        runpy.run_path("benchmarks/report.py", run_name="__main__")
