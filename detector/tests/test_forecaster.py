import os
import sys
import time

# Add parent directory to path so imports work cleanly in test suite
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.forecaster import TrendForecaster
from scraper import MetricWindow


def make_mock_window(
    service: str,
    timestamp: float,
    p99_latency: float,
    error_rate: float = 0.0,
    cpu: float = 0.1,
    memory: float = 13421772.8,
) -> MetricWindow:
    return MetricWindow(
        service_name=service,
        timestamp=timestamp,
        feature_vector={
            "p50_latency": p99_latency / 2,
            "p95_latency": p99_latency * 0.9,
            "p99_latency": p99_latency,
            "request_rate": 100.0,
            "error_rate": error_rate,
            "cpu_usage": cpu,
            "memory_usage": memory,
            "pod_restarts": 0.0,
        },
    )


def test_trend_forecaster_buffer_limit():
    forecaster = TrendForecaster()
    # Fill buffer with 150 windows
    t = time.time()
    for i in range(150):
        window = make_mock_window("frontend", t + i * 15.0, 0.1)
        forecaster.update(window)

    assert len(forecaster.buffers["frontend"]) == 120


def test_trend_forecaster_no_breach():
    forecaster = TrendForecaster()
    t = time.time()
    # Constant normal latency (100ms)
    for i in range(10):
        window = make_mock_window("frontend", t + i * 15.0, 0.1)
        forecaster.update(window)

    # SLO is default 500ms. Latency is constant at 100ms. No breach predicted.
    alert = forecaster.predict_breach("frontend")
    assert alert is None


def test_trend_forecaster_p99_latency_breach():
    forecaster = TrendForecaster()
    t = time.time()
    # Increasing latency linearly from 100ms to 280ms
    # SLO threshold = 500ms
    # With 10 windows, the next 20 windows (horizon_steps = 20, 300s) will breach
    for i in range(10):
        latency = 0.10 + i * 0.02  # 100ms to 280ms
        window = make_mock_window("frontend", t + i * 15.0, latency)
        forecaster.update(window)

    alert = forecaster.predict_breach("frontend")
    assert alert is not None
    assert alert.service == "frontend"
    assert alert.metric == "p99_latency"
    assert alert.type == "predictive"
    assert alert.predicted_value > 500.0
    assert alert.time_to_breach_seconds > 0.0
    assert alert.confidence > 0.95


def test_trend_forecaster_low_confidence_suppression():
    forecaster = TrendForecaster()
    t = time.time()
    # Random highly volatile latency values (low R2)
    import random

    random.seed(42)
    for i in range(10):
        latency = 0.3 + random.uniform(-0.25, 0.25)
        window = make_mock_window("frontend", t + i * 15.0, latency)
        forecaster.update(window)

    alert = forecaster.predict_breach("frontend")
    # Volatile metrics should not generate predictive alerts due to R² check
    assert alert is None


def test_trend_forecaster_deduplication():
    forecaster = TrendForecaster()
    t = time.time()
    # Populate initial breaching sequence
    for i in range(10):
        latency = 0.10 + i * 0.02
        window = make_mock_window("frontend", t + i * 15.0, latency)
        forecaster.update(window)

    alert1 = forecaster.predict_breach("frontend")
    assert alert1 is not None

    # Try immediately predicting again (same time) - should be suppressed
    alert2 = forecaster.predict_breach("frontend")
    assert alert2 is None

    # Add a new window slightly after (e.g. 15s) - still suppressed
    window_new = make_mock_window("frontend", t + 10 * 15.0, 0.30)
    forecaster.update(window_new)
    alert3 = forecaster.predict_breach("frontend")
    assert alert3 is None
