import sys
import os
import time
# Add parent directory to path so imports work cleanly in test suite
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from scraper import MetricWindow
from alerter import Alerter, Alert

def create_mock_window(service: str, error_rate: float = 0.0, pod_restarts: float = 0.0) -> MetricWindow:
    return MetricWindow(
        service_name=service,
        timestamp=time.time(),
        feature_vector={
            "p50_latency": 0.02,
            "p95_latency": 0.05,
            "p99_latency": 0.10,
            "request_rate": 100.0,
            "error_rate": error_rate,
            "cpu_usage": 0.5,
            "memory_usage": 128e6,
            "pod_restarts": pod_restarts
        }
    )

def test_alerter_severity_classification():
    # Deduplication window 5m, we bypass it for distinct services/initial alarms
    alerter = Alerter(deduplication_window_seconds=300)
    
    # 1. Non-anomaly should yield None
    win_normal = create_mock_window("frontend")
    alert = alerter.process_window(win_normal, anomaly_score=-0.1, is_anomaly=False)
    assert alert is None

    # Reset alerter dict to bypass deduplication for separate test cases
    # 2. P1: score < -0.5 AND error_rate > 0.1
    win_p1_err = create_mock_window("frontend", error_rate=0.15)
    alerter.last_alerted.clear()
    alert_p1_err = alerter.process_window(win_p1_err, anomaly_score=-0.55, is_anomaly=True)
    assert alert_p1_err is not None
    assert alert_p1_err.severity == "P1"
    assert alert_p1_err.service == "frontend"
    assert alert_p1_err.anomaly_score == -0.55

    # 3. P1: score < -0.5 AND restarts > 3
    win_p1_rest = create_mock_window("frontend", pod_restarts=4.0)
    alerter.last_alerted.clear()
    alert_p1_rest = alerter.process_window(win_p1_rest, anomaly_score=-0.6, is_anomaly=True)
    assert alert_p1_rest is not None
    assert alert_p1_rest.severity == "P1"

    # 4. P2: score < -0.3 but not P1 conditions
    win_p2 = create_mock_window("frontend", error_rate=0.02, pod_restarts=0.0)
    alerter.last_alerted.clear()
    alert_p2 = alerter.process_window(win_p2, anomaly_score=-0.35, is_anomaly=True)
    assert alert_p2 is not None
    assert alert_p2.severity == "P2"

    # 5. P3: score > -0.3 but is anomalous (extreme point anomaly that doesn't breach P2 limits)
    win_p3 = create_mock_window("frontend", error_rate=0.0, pod_restarts=0.0)
    alerter.last_alerted.clear()
    alert_p3 = alerter.process_window(win_p3, anomaly_score=-0.25, is_anomaly=True)
    assert alert_p3 is not None
    assert alert_p3.severity == "P3"

def test_alerter_deduplication():
    alerter = Alerter(deduplication_window_seconds=10.0) # 10 seconds for test
    
    win = create_mock_window("frontend")
    
    # First alert should fire
    alert1 = alerter.process_window(win, anomaly_score=-0.4, is_anomaly=True)
    assert alert1 is not None
    
    # Second alert within deduplication window should be suppressed
    alert2 = alerter.process_window(win, anomaly_score=-0.4, is_anomaly=True)
    assert alert2 is None
    
    # Alert for a DIFFERENT service should fire
    win_backend = create_mock_window("backend")
    alert_backend = alerter.process_window(win_backend, anomaly_score=-0.4, is_anomaly=True)
    assert alert_backend is not None
    
    # Wait for deduplication window to expire
    alerter.last_alerted["frontend"] = time.time() - 15.0 # force expiry
    
    # Alert should now fire again
    alert3 = alerter.process_window(win, anomaly_score=-0.4, is_anomaly=True)
    assert alert3 is not None
