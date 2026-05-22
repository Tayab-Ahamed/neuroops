import sys
import os
import datetime
# Add parent directory to path so imports work cleanly in test suite
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch
from scraper import PrometheusScraper
from baseline_collector import collect_historical_baseline

@patch("scraper.PrometheusConnect")
def test_collect_historical_baseline(mock_prom_conn):
    # Setup mock connections and returned queries
    mock_connect = mock_prom_conn.return_value
    scraper = PrometheusScraper(prometheus_url="http://mock-prometheus:9090")
    
    # Mock custom_query_range response
    # The format returned is a list of dicts: [{'metric': {...}, 'values': [[timestamp, value_str]]}]
    mock_connect.custom_query_range.side_effect = lambda query, start_time, end_time, step: {
        "sum(rate(http_requests_total[1m])) by (job)": [
            {"metric": {"job": "frontend-service"}, "values": [[1684000000.0, "100.0"]]},
            {"metric": {"job": "backend-service"}, "values": [[1684000000.0, "50.0"]]}
        ],
        'sum(rate(http_requests_total{status=~"5.."}[1m])) by (job)': [
            {"metric": {"job": "frontend-service"}, "values": [[1684000000.0, "10.0"]]}
        ],
        "histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[1m])) by (le, job))": [
            {"metric": {"job": "frontend-service"}, "values": [[1684000000.0, "0.05"]]},
            {"metric": {"job": "backend-service"}, "values": [[1684000000.0, "0.02"]]}
        ]
    }.get(query, [])

    windows = collect_historical_baseline(scraper, minutes=5, step_seconds=15)
    
    # Check that baseline windows were constructed successfully
    assert len(windows) > 0
    
    # Index by service name
    frontend_windows = [w for w in windows if w.service_name == "frontend"]
    assert len(frontend_windows) == 1
    
    # Check frontend features
    features = frontend_windows[0].feature_vector
    assert features["request_rate"] == 100.0
    assert features["error_rate"] == 0.1 # 10.0 / 100.0
    assert features["p50_latency"] == 0.05

@patch("scraper.PrometheusConnect")
def test_collect_historical_baseline_edge_cases(mock_prom_conn):
    mock_connect = mock_prom_conn.return_value
    scraper = PrometheusScraper(prometheus_url="http://mock-prometheus:9090")
    
    # 1. Test custom_query_range failure exception handling
    mock_connect.custom_query_range.side_effect = Exception("Range query error")
    windows = collect_historical_baseline(scraper, minutes=5, step_seconds=15)
    assert len(windows) == 0

    # 2. Test values array length mismatch, missing job label, invalid float values, non-matching service
    mock_connect.custom_query_range.side_effect = lambda query, start_time, end_time, step: {
        "sum(rate(http_requests_total[1m])) by (job)": [
            # Missing job label
            {"metric": {}, "values": [[1684000000.0, "100.0"]]},
            # Non-matching service (line 67 coverage)
            {"metric": {"job": "external-service"}, "values": [[1684000000.0, "100.0"]]},
            # Invalid values format (length is not 2)
            {"metric": {"job": "frontend-service"}, "values": [[1684000000.0] , []]},
            # Invalid float value
            {"metric": {"job": "frontend-service"}, "values": [[1684000000.0, "not-a-float-val"]]}
        ]
    }.get(query, [])
    
    windows = collect_historical_baseline(scraper, minutes=5, step_seconds=15)
    # The invalid value array formats/types and non-matching services should be skipped or default to 0.0, but still generate MetricWindow
    assert len(windows) > 0

@patch("baseline_collector.collect_historical_baseline")
@patch("baseline_collector.IsolationForestModel")
@patch("baseline_collector.PrometheusScraper")
def test_main_cli_execution(mock_scraper, mock_model, mock_collect):
    import baseline_collector
    
    # Mock return values for success case
    mock_collect.return_value = [MagicMock(service_name="frontend")]
    
    test_args = ["baseline_collector.py", "--minutes", "10", "--step", "15", "--output", "test_isolation_forest.joblib"]
    with patch("sys.argv", test_args):
        baseline_collector.main()
        
    mock_collect.assert_called_once()
    mock_model.return_value.fit.assert_called_once()
    mock_model.return_value.save.assert_called_once_with("test_isolation_forest.joblib")

    # Test main empty collector list exit failure case
    mock_collect.return_value = []
    with patch("sys.argv", test_args), pytest.raises(SystemExit) as exc_info:
        baseline_collector.main()
    assert exc_info.value.code == 1
