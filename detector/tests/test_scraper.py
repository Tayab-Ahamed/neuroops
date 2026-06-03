import os
import sys

# Add parent directory to path so imports work cleanly in test suite
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from scraper import PrometheusScraper


def test_normalize_service_name():
    scraper = PrometheusScraper(prometheus_url="http://mock-prometheus:9090")

    assert scraper._normalize_service_name("frontend-service") == "frontend"
    assert scraper._normalize_service_name("neuroops-backend") == "backend"
    assert scraper._normalize_service_name("database-stub-deploy") == "database-stub"
    assert scraper._normalize_service_name("database") == "database-stub"
    assert scraper._normalize_service_name("unknown-job") is None


@patch("scraper.PrometheusConnect")
def test_scrape_metrics_parsing(mock_prom_conn):
    # Setup mock connections and returned queries
    mock_connect = mock_prom_conn.return_value
    scraper = PrometheusScraper(prometheus_url="http://mock-prometheus:9090")

    # Create mock metrics response
    # Format returned by custom_query is a list of dicts: [{'metric': {...}, 'value': [timestamp, str_val]}]
    mock_connect.custom_query.side_effect = lambda query: {
        "sum(rate(http_requests_total[1m])) by (job)": [
            {"metric": {"job": "frontend-service"}, "value": [1684000000, "100.0"]},
            {"metric": {"job": "backend-service"}, "value": [1684000000, "50.0"]},
        ],
        'sum(rate(http_requests_total{status=~"5.."}[1m])) by (job)': [
            {"metric": {"job": "frontend-service"}, "value": [1684000000, "10.0"]}
        ],
        "histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[1m])) by (le, job))": [
            {"metric": {"job": "frontend-service"}, "value": [1684000000, "0.05"]},
            {"metric": {"job": "backend-service"}, "value": [1684000000, "0.02"]},
        ],
        "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le, job))": [
            {"metric": {"job": "frontend-service"}, "value": [1684000000, "0.15"]}
        ],
        "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[1m])) by (le, job))": [
            {"metric": {"job": "frontend-service"}, "value": [1684000000, "0.30"]}
        ],
        'sum(rate(container_cpu_usage_seconds_total{container!="",namespace="neuroops-demo"}[1m])) by (container)': [
            {"metric": {"container": "frontend"}, "value": [1684000000, "0.85"]},
            {"metric": {"container": "backend"}, "value": [1684000000, "0.45"]},
        ],
        'sum(container_memory_working_set_bytes{container!="",namespace="neuroops-demo"}) by (container)': [
            {"metric": {"container": "frontend"}, "value": [1684000000, "134217728.0"]}  # 128MB
        ],
        'sum(delta(kube_pod_container_status_restarts_total{container!="",namespace="neuroops-demo"}[1m])) by (container)': [
            {"metric": {"container": "frontend"}, "value": [1684000000, "1.0"]}
        ],
    }.get(query, [])

    windows = scraper.scrape_metrics()

    # We target 3 services: frontend, backend, database-stub
    assert len(windows) == 3

    # Index by service name
    svc_map = {w.service_name: w for w in windows}

    # Check frontend parsed correctly
    frontend_features = svc_map["frontend"].feature_vector
    assert frontend_features["request_rate"] == 100.0
    assert frontend_features["error_rate"] == 0.1  # 10.0 / 100.0
    assert frontend_features["p50_latency"] == 0.05
    assert frontend_features["p95_latency"] == 0.15
    assert frontend_features["p99_latency"] == 0.30
    assert frontend_features["cpu_usage"] == 0.85
    assert frontend_features["memory_usage"] == 134217728.0
    assert frontend_features["pod_restarts"] == 1.0

    # Check backend parsed correctly
    backend_features = svc_map["backend"].feature_vector
    assert backend_features["request_rate"] == 50.0
    assert backend_features["error_rate"] == 0.0  # No errors in sideloaded response
    assert backend_features["p50_latency"] == 0.02
    assert backend_features["cpu_usage"] == 0.45


@patch("scraper.PrometheusConnect")
def test_scrape_metrics_exceptions_and_edge_cases(mock_prom_conn):
    mock_connect = mock_prom_conn.return_value
    scraper = PrometheusScraper(prometheus_url="http://mock-prometheus:9090")

    # 1. Test custom_query failure exception handling
    mock_connect.custom_query.side_effect = Exception("Prometheus connection timeout!")
    assert scraper._run_query("some_query") == []

    # 2. Test float conversion ValueError, missing labels, and non-target service normalization
    mock_connect.custom_query.side_effect = lambda query: {
        "sum(rate(http_requests_total[1m])) by (job)": [
            # ValueError: value cannot be converted to float
            {"metric": {"job": "frontend-service"}, "value": [1684000000, "invalid-float-value"]},
            # Missing labels: no job or container
            {"metric": {}, "value": [1684000000, "100.0"]},
            # Non-target service name: external-service
            {"metric": {"job": "external-service"}, "value": [1684000000, "100.0"]},
        ]
    }.get(query, [])

    windows = scraper.scrape_metrics()
    assert len(windows) == 3
    # Check that frontend is parsed but request_rate is 0.0 because of the float conversion error
    svc_map = {w.service_name: w for w in windows}
    assert svc_map["frontend"].feature_vector["request_rate"] == 0.0
