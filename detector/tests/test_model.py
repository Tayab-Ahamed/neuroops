import os
import sys

# Add parent directory to path so imports work cleanly in test suite
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from models.isolation_forest import IsolationForestModel
from scraper import MetricWindow


def create_synthetic_window(
    service: str, cpu: float, memory: float, error_rate: float = 0.0
) -> MetricWindow:
    return MetricWindow(
        service_name=service,
        timestamp=1684000000.0,
        feature_vector={
            "p50_latency": 0.02,
            "p95_latency": 0.05,
            "p99_latency": 0.10,
            "request_rate": 80.0,
            "error_rate": error_rate,
            "cpu_usage": cpu,
            "memory_usage": memory,
            "pod_restarts": 0.0,
        },
    )


def test_model_fit_score_predict():
    # 1. Create a baseline dataset (normal behavior)
    baseline_windows = []

    # Generate 30 normal samples for frontend
    for _ in range(30):
        # Add slight noise to keep it realistic
        cpu = float(np.random.normal(0.4, 0.05))
        mem = float(np.random.normal(128e6, 5e6))
        baseline_windows.append(create_synthetic_window("frontend", cpu, mem))

    # Generate 30 normal samples for backend
    for _ in range(30):
        cpu = float(np.random.normal(0.3, 0.03))
        mem = float(np.random.normal(256e6, 10e6))
        baseline_windows.append(create_synthetic_window("backend", cpu, mem))

    # 2. Fit models
    model = IsolationForestModel(contamination=0.05)
    model.fit(baseline_windows)

    # Assert models are fitted
    assert "frontend" in model.models
    assert "backend" in model.models
    assert "database-stub" not in model.models  # None trained for database-stub

    # 3. Test scoring and prediction for normal sample
    normal_sample = create_synthetic_window("frontend", 0.41, 127e6)
    score_normal = model.score(normal_sample)
    is_anomaly_normal = model.predict(normal_sample)

    # Score should be close to 0 (normal, since score_samples returns negative anomaly score in Isolation Forest, e.g. > -0.5)
    assert score_normal > -0.5
    assert is_anomaly_normal is False

    # 4. Test scoring and prediction for anomalous sample (extreme CPU/Memory/Error spike)
    anomalous_sample = create_synthetic_window("frontend", 5.0, 500e6, error_rate=0.9)
    score_anomaly = model.score(anomalous_sample)
    is_anomaly_anomaly = model.predict(anomalous_sample)

    # Anomaly score should be lower than the normal sample
    assert score_anomaly < score_normal
    assert is_anomaly_anomaly is True

    # 5. Check missing model fallback
    missing_sample = create_synthetic_window("database-stub", 0.1, 64e6)
    assert model.score(missing_sample) == 0.0
    assert model.predict(missing_sample) is False


def test_model_save_load(tmp_path):
    # Train a quick model
    baseline = [create_synthetic_window("frontend", 0.4, 128e6) for _ in range(10)]
    model = IsolationForestModel(contamination=0.1)
    model.fit(baseline)

    # Save model
    save_path = os.path.join(tmp_path, "isolation_forest.joblib")
    model.save(save_path)
    assert os.path.exists(save_path)

    # Load model
    loaded_model = IsolationForestModel()
    loaded_model.load(save_path)

    assert loaded_model.contamination == 0.1
    assert "frontend" in loaded_model.models
    assert loaded_model.features == model.features


def test_model_load_non_existent_file():
    model = IsolationForestModel()
    with pytest.raises(FileNotFoundError):
        model.load("non_existent_model_file_path.joblib")
