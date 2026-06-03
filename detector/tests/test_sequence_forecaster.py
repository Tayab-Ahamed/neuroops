import sys
import os
# Add parent directory to path so imports work cleanly in test suite
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
from scraper import MetricWindow
from models.sequence_forecaster import SequenceForecastModel

def create_synthetic_window(service: str, cpu: float, memory: float, error_rate: float = 0.0) -> MetricWindow:
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
            "pod_restarts": 0.0
        }
    )

def test_sequence_forecaster_fit_score_predict():
    # 1. Create sequential baseline dataset (normal steady behavior)
    baseline_windows = []
    
    # Generate 15 sequential windows for frontend (needs sequence_length=5 + some baseline windows)
    for i in range(15):
        # Normal steady value with tiny noise
        cpu = 0.4 + 0.01 * np.sin(i)
        mem = 128e6 + 1e5 * np.cos(i)
        baseline_windows.append(create_synthetic_window("frontend", float(cpu), float(mem)))

    # 2. Fit model
    model = SequenceForecastModel(sequence_length=5)
    model.fit(baseline_windows)
    
    # Assert models are fitted and threshold is established
    assert "frontend" in model.models
    assert "frontend" in model.thresholds
    
    # 3. Create a normal sequence
    seq = [create_synthetic_window("frontend", 0.4, 128e6) for _ in range(5)]
    next_normal = create_synthetic_window("frontend", 0.4, 128e6)
    
    score_normal = model.score(seq, next_normal)
    is_anomaly_normal = model.predict(seq, next_normal)
    
    # Score should be very low (normal prediction error)
    assert score_normal >= 0.0
    assert is_anomaly_normal is False
    
    # 4. Test anomalous sequence step (massive spike in next step)
    next_anom = create_synthetic_window("frontend", 4.0, 500e6, error_rate=0.8)
    score_anom = model.score(seq, next_anom)
    is_anomaly_anom = model.predict(seq, next_anom)
    
    assert score_anom > score_normal
    assert is_anomaly_anom is True

def test_sequence_forecaster_save_load(tmp_path):
    baseline = [create_synthetic_window("frontend", 0.4, 128e6) for _ in range(10)]
    model = SequenceForecastModel(sequence_length=5)
    model.fit(baseline)
    
    save_path = os.path.join(tmp_path, "seq_model.joblib")
    model.save(save_path)
    assert os.path.exists(save_path)
    
    loaded = SequenceForecastModel()
    loaded.load(save_path)
    
    assert loaded.sequence_length == 5
    assert "frontend" in loaded.models
    assert "frontend" in loaded.thresholds
    assert loaded.features == model.features

def test_sequence_forecaster_load_non_existent_file():
    model = SequenceForecastModel()
    with pytest.raises(FileNotFoundError):
        model.load("non_existent_seq_model_path.joblib")
