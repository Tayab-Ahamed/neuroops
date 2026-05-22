import pytest
import datetime
from unittest.mock import MagicMock, patch
from tools import k8s_tools, github_tools, prometheus_tools, jaeger_tools

# ==========================================
# 1. KUBERNETES TOOLS TESTS
# ==========================================

def test_k8s_get_pod_status_mock():
    # Force mock mode
    k8s_tools.k8s_configured = False
    
    # 1. Test OOM pod name
    res_oom = k8s_tools.get_pod_status.invoke({"namespace": "default", "pod_name": "backend-oom-123"})
    assert "OOMKilled" in res_oom
    
    # 2. Test Crash pod name
    res_crash = k8s_tools.get_pod_status.invoke({"namespace": "default", "pod_name": "backend-crash-123"})
    assert "CrashLoopBackOff" in res_crash
    
    # 3. Test default pod name
    res_normal = k8s_tools.get_pod_status.invoke({"namespace": "default", "pod_name": "backend-normal"})
    assert "Running" in res_normal

@patch("tools.k8s_tools.client.CoreV1Api")
def test_k8s_get_pod_status_live(mock_core_api):
    # Force live mode
    k8s_tools.k8s_configured = True
    
    # Mock pod object
    mock_pod = MagicMock()
    mock_pod.status.phase = "Running"
    
    mock_cs = MagicMock()
    mock_cs.restart_count = 5
    mock_pod.status.container_statuses = [mock_cs]
    
    mock_cond = MagicMock()
    mock_cond.type = "Ready"
    mock_cond.status = "True"
    mock_pod.status.conditions = [mock_cond]
    
    # Mock event objects
    mock_event = MagicMock()
    mock_event.last_timestamp = "2026-05-22T17:00:00"
    mock_event.message = "Successfully pulled image"
    mock_events_list = MagicMock()
    mock_events_list.items = [mock_event]
    
    # Set up api mock
    mock_api_instance = MagicMock()
    mock_api_instance.read_namespaced_pod.return_value = mock_pod
    mock_api_instance.list_namespaced_event.return_value = mock_events_list
    mock_core_api.return_value = mock_api_instance
    
    res = k8s_tools.get_pod_status.invoke({"namespace": "default", "pod_name": "backend-pod"})
    assert "Phase: Running" in res
    assert "Restarts: 5" in res
    assert "Ready=True" in res
    assert "Successfully pulled image" in res

@patch("tools.k8s_tools.client.CoreV1Api")
def test_k8s_get_pod_status_live_error(mock_core_api):
    k8s_tools.k8s_configured = True
    
    mock_api_instance = MagicMock()
    mock_api_instance.read_namespaced_pod.side_effect = Exception("API error")
    mock_core_api.return_value = mock_api_instance
    
    res = k8s_tools.get_pod_status.invoke({"namespace": "default", "pod_name": "backend-pod"})
    assert "Error querying pod status" in res
    assert "API error" in res

def test_k8s_get_deployment_history_mock():
    k8s_tools.k8s_configured = False
    res = k8s_tools.get_deployment_history.invoke({"namespace": "default", "deployment_name": "backend"})
    assert "Revision 3: Rolled out image neuroops/backend:v1.2.0" in res

@patch("tools.k8s_tools.client.AppsV1Api")
def test_k8s_get_deployment_history_live(mock_apps_api):
    k8s_tools.k8s_configured = True
    
    # Mock deployment
    mock_dep = MagicMock()
    mock_dep.status.replicas = 3
    mock_dep.status.updated_replicas = 3
    mock_dep.status.ready_replicas = 3
    mock_dep.status.available_replicas = 3
    mock_dep.spec.selector.match_labels = {"app": "backend"}
    
    # Mock replicaset
    mock_rs = MagicMock()
    mock_rs.metadata.annotations = {"deployment.kubernetes.io/revision": "2"}
    mock_rs.metadata.name = "backend-555"
    mock_container = MagicMock()
    mock_container.image = "neuroops/backend:v1.2.0"
    mock_rs.spec.template.spec.containers = [mock_container]
    
    mock_rs_list = MagicMock()
    mock_rs_list.items = [mock_rs]
    
    mock_api_instance = MagicMock()
    mock_api_instance.read_namespaced_deployment.return_value = mock_dep
    mock_api_instance.list_namespaced_replica_set.return_value = mock_rs_list
    mock_apps_api.return_value = mock_api_instance
    
    res = k8s_tools.get_deployment_history.invoke({"namespace": "default", "deployment_name": "backend"})
    assert "Replicas: 3 desired" in res
    assert "Revision 2: Image: neuroops/backend:v1.2.0" in res

@patch("tools.k8s_tools.client.AppsV1Api")
def test_k8s_get_deployment_history_live_error(mock_apps_api):
    k8s_tools.k8s_configured = True
    
    mock_api_instance = MagicMock()
    mock_api_instance.read_namespaced_deployment.side_effect = Exception("Apps API error")
    mock_apps_api.return_value = mock_api_instance
    
    res = k8s_tools.get_deployment_history.invoke({"namespace": "default", "deployment_name": "backend"})
    assert "Error querying deployment history" in res
    assert "Apps API error" in res

def test_k8s_get_recent_events_mock():
    k8s_tools.k8s_configured = False
    res = k8s_tools.get_recent_events.invoke({"namespace": "default", "service_name": "backend", "minutes": 10})
    assert "Recent Events in default" in res
    assert "Liveness probe failed" in res

@patch("tools.k8s_tools.client.CoreV1Api")
def test_k8s_get_recent_events_live(mock_core_api):
    k8s_tools.k8s_configured = True
    
    # Create timezone-aware datetime for events
    now = datetime.datetime.now(datetime.timezone.utc)
    recent_time = now - datetime.timedelta(minutes=2)
    old_time = now - datetime.timedelta(minutes=20)
    
    # Event 1: Recent matching
    mock_e1 = MagicMock()
    mock_e1.last_timestamp = recent_time
    mock_e1.involved_object.name = "backend-service"
    mock_e1.type = "Warning"
    mock_e1.message = "Failed liveness probe"
    
    # Event 2: Old matching (should be skipped)
    mock_e2 = MagicMock()
    mock_e2.last_timestamp = old_time
    mock_e2.involved_object.name = "backend-service"
    mock_e2.type = "Warning"
    mock_e2.message = "Failed startup probe"
    
    # Event 3: No timestamp (should be skipped)
    mock_e3 = MagicMock()
    mock_e3.last_timestamp = None
    mock_e3.event_time = None
    mock_e3.first_timestamp = None
    
    # Event 4: Naive timestamp (should be parsed safely)
    mock_e4 = MagicMock()
    mock_e4.last_timestamp = datetime.datetime.now()  # naive
    mock_e4.involved_object.name = "frontend"
    mock_e4.type = "Normal"
    mock_e4.message = "Started backend related container"
    
    mock_events_list = MagicMock()
    mock_events_list.items = [mock_e1, mock_e2, mock_e3, mock_e4]
    
    mock_api_instance = MagicMock()
    mock_api_instance.list_namespaced_event.return_value = mock_events_list
    mock_core_api.return_value = mock_api_instance
    
    # Search for backend
    res = k8s_tools.get_recent_events.invoke({"namespace": "default", "service_name": "backend", "minutes": 10})
    assert "Recent Events in default" in res
    assert "Failed liveness probe" in res
    assert "Started backend related container" in res
    assert "Failed startup probe" not in res

@patch("tools.k8s_tools.client.CoreV1Api")
def test_k8s_get_recent_events_live_no_matches(mock_core_api):
    k8s_tools.k8s_configured = True
    
    mock_events_list = MagicMock()
    mock_events_list.items = []
    
    mock_api_instance = MagicMock()
    mock_api_instance.list_namespaced_event.return_value = mock_events_list
    mock_core_api.return_value = mock_api_instance
    
    res = k8s_tools.get_recent_events.invoke({"namespace": "default", "service_name": "backend", "minutes": 10})
    assert "No events found for backend" in res

@patch("tools.k8s_tools.client.CoreV1Api")
def test_k8s_get_recent_events_live_error(mock_core_api):
    k8s_tools.k8s_configured = True
    
    mock_api_instance = MagicMock()
    mock_api_instance.list_namespaced_event.side_effect = Exception("Events API error")
    mock_core_api.return_value = mock_api_instance
    
    res = k8s_tools.get_recent_events.invoke({"namespace": "default", "service_name": "backend", "minutes": 10})
    assert "Error querying events" in res
    assert "Events API error" in res


# ==========================================
# 2. GITHUB TOOLS TESTS
# ==========================================

def test_github_get_recent_deploys_mock():
    github_tools.github_configured = False
    res = github_tools.get_recent_deploys.invoke({"repo": "neuroops/org", "minutes": 60})
    assert "Recent deployments & commits in neuroops/org" in res
    assert "Commit: a1b2c3d4e5f6" in res

@patch("tools.github_tools.Github")
def test_github_get_recent_deploys_live(mock_github_class):
    github_tools.github_configured = True
    github_tools.github_token = "some-token"
    
    mock_commit_info = MagicMock()
    mock_commit_info.sha = "1234567890abcdef"
    mock_commit_info.commit.author.name = "Bob Jones"
    mock_commit_info.commit.author.email = "bob@neuroops.io"
    # Ensure timezone naive datetime to test replacement path
    mock_commit_info.commit.author.date = datetime.datetime.now()
    mock_commit_info.commit.message = "fix(backend): database memory leak"
    
    mock_repo = MagicMock()
    mock_repo.get_commits.return_value = [mock_commit_info]
    
    mock_g_instance = MagicMock()
    mock_g_instance.get_repo.return_value = mock_repo
    mock_github_class.return_value = mock_g_instance
    
    res = github_tools.get_recent_deploys.invoke({"repo": "neuroops/org", "minutes": 60})
    assert "Commit: 1234567890ab" in res
    assert "Bob Jones" in res
    assert "database memory leak" in res

@patch("tools.github_tools.Github")
def test_github_get_recent_deploys_live_empty(mock_github_class):
    github_tools.github_configured = True
    github_tools.github_token = "some-token"
    
    mock_repo = MagicMock()
    mock_repo.get_commits.return_value = []
    
    mock_g_instance = MagicMock()
    mock_g_instance.get_repo.return_value = mock_repo
    mock_github_class.return_value = mock_g_instance
    
    res = github_tools.get_recent_deploys.invoke({"repo": "neuroops/org", "minutes": 60})
    assert "No deployments or commits found" in res

@patch("tools.github_tools.Github")
def test_github_get_recent_deploys_live_error(mock_github_class):
    github_tools.github_configured = True
    github_tools.github_token = "some-token"
    
    mock_g_instance = MagicMock()
    mock_g_instance.get_repo.side_effect = Exception("GitHub API down")
    mock_github_class.return_value = mock_g_instance
    
    res = github_tools.get_recent_deploys.invoke({"repo": "neuroops/org", "minutes": 60})
    assert "Error querying GitHub deployments" in res
    assert "GitHub API down" in res


# ==========================================
# 3. PROMETHEUS TOOLS TESTS
# ==========================================

def test_prometheus_query_metric_mock():
    prometheus_tools.prom_configured = False
    res = prometheus_tools.query_metric.invoke({"promql": "up{job='backend'}", "minutes": 10})
    assert "PromQL Query: up{job='backend'}" in res

@patch("tools.prometheus_tools.PrometheusConnect")
def test_prometheus_query_metric_live(mock_prom_class):
    prometheus_tools.prom_configured = True
    
    mock_res = [
        {
            "metric": {"job": "backend-service"},
            "values": [[1716390000, "1.0"]]
        }
    ]
    
    mock_prom_instance = MagicMock()
    mock_prom_instance.custom_query_range.return_value = mock_res
    mock_prom_class.return_value = mock_prom_instance
    # Patch the global 'prom' variable to use the mocked instance
    with patch("tools.prometheus_tools.prom", mock_prom_instance):
        res = prometheus_tools.query_metric.invoke({"promql": "up", "minutes": 10})
        assert "Metric: {'job': 'backend-service'}" in res
        assert "1716390000: 1.0" in res

@patch("tools.prometheus_tools.PrometheusConnect")
def test_prometheus_query_metric_live_empty(mock_prom_class):
    prometheus_tools.prom_configured = True
    
    mock_prom_instance = MagicMock()
    mock_prom_instance.custom_query_range.return_value = []
    mock_prom_class.return_value = mock_prom_instance
    
    with patch("tools.prometheus_tools.prom", mock_prom_instance):
        res = prometheus_tools.query_metric.invoke({"promql": "up", "minutes": 10})
        assert "No metrics returned for query: up" in res

@patch("tools.prometheus_tools.PrometheusConnect")
def test_prometheus_query_metric_live_error(mock_prom_class):
    prometheus_tools.prom_configured = True
    
    mock_prom_instance = MagicMock()
    mock_prom_instance.custom_query_range.side_effect = Exception("Prometheus error")
    mock_prom_class.return_value = mock_prom_instance
    
    with patch("tools.prometheus_tools.prom", mock_prom_instance):
        res = prometheus_tools.query_metric.invoke({"promql": "up", "minutes": 10})
        assert "Error executing PromQL query up" in res
        assert "Prometheus error" in res

def test_prometheus_compare_services_mock():
    prometheus_tools.prom_configured = False
    
    res_error = prometheus_tools.compare_services.invoke({"metric": "error", "time_window": "5m"})
    assert "Error Rate" in res_error
    assert "backend: 0.22" in res_error
    
    res_latency = prometheus_tools.compare_services.invoke({"metric": "latency", "time_window": "5m"})
    assert "P95 Latency" in res_latency
    assert "frontend: 2.15s" in res_latency
    
    res_cpu = prometheus_tools.compare_services.invoke({"metric": "cpu", "time_window": "5m"})
    assert "Saturation" in res_cpu
    assert "backend: CPU: 95%" in res_cpu
    
    res_traffic = prometheus_tools.compare_services.invoke({"metric": "traffic", "time_window": "5m"})
    assert "Traffic" in res_traffic
    assert "frontend: 120 req/sec" in res_traffic

@patch("tools.prometheus_tools.PrometheusConnect")
def test_prometheus_compare_services_live(mock_prom_class):
    prometheus_tools.prom_configured = True
    
    mock_prom_instance = MagicMock()
    # Mock return value for custom_query
    mock_prom_instance.custom_query.return_value = [{"value": [1716390000, "0.05"]}]
    mock_prom_class.return_value = mock_prom_instance
    
    with patch("tools.prometheus_tools.prom", mock_prom_instance):
        res_latency = prometheus_tools.compare_services.invoke({"metric": "latency", "time_window": "5m"})
        assert "Comparison" in res_latency
        assert "frontend: 0.05" in res_latency
        
        res_error = prometheus_tools.compare_services.invoke({"metric": "error", "time_window": "5m"})
        assert "Comparison" in res_error
        assert "backend: 0.05" in res_error
        
        res_cpu = prometheus_tools.compare_services.invoke({"metric": "cpu", "time_window": "5m"})
        assert "Comparison" in res_cpu
        
        res_traffic = prometheus_tools.compare_services.invoke({"metric": "traffic", "time_window": "5m"})
        assert "Comparison" in res_traffic

@patch("tools.prometheus_tools.PrometheusConnect")
def test_prometheus_compare_services_live_error(mock_prom_class):
    prometheus_tools.prom_configured = True
    
    mock_prom_instance = MagicMock()
    mock_prom_instance.custom_query.side_effect = Exception("Query error")
    mock_prom_class.return_value = mock_prom_instance
    
    with patch("tools.prometheus_tools.prom", mock_prom_instance):
        res = prometheus_tools.compare_services.invoke({"metric": "latency", "time_window": "5m"})
        assert "Error executing compare_services" in res
        assert "Query error" in res


# ==========================================
# 4. JAEGER TOOLS TESTS
# ==========================================

def test_jaeger_get_service_dependencies_mock():
    jaeger_tools.jaeger_configured = False
    
    res_front = jaeger_tools.get_service_dependencies.invoke({"service_name": "frontend"})
    assert "upstream_services" not in res_front # wait, mock format matches jaeger_tools.py: Service Dependency Analysis for frontend
    assert "Service Dependency Analysis for frontend" in res_front
    assert "Bottleneck: backend-service" in res_front
    
    res_back = jaeger_tools.get_service_dependencies.invoke({"service_name": "backend"})
    assert "Upstream: frontend-service" in res_back
    assert "Bottleneck: backend-service self-latency" in res_back
    
    res_db = jaeger_tools.get_service_dependencies.invoke({"service_name": "database"})
    assert "Upstream: backend-service" in res_db
    assert "Bottleneck: None" in res_db

@patch("tools.jaeger_tools.httpx.get")
def test_jaeger_get_service_dependencies_live(mock_http_get):
    jaeger_tools.jaeger_configured = True
    
    # Mock success response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"parent": "frontend", "child": "backend", "callCount": 10},
            {"parent": "backend", "child": "database", "callCount": 20}
        ]
    }
    mock_http_get.return_value = mock_response
    
    res = jaeger_tools.get_service_dependencies.invoke({"service_name": "backend"})
    assert "Upstream: frontend" in res
    assert "Downstream: database" in res

@patch("tools.jaeger_tools.httpx.get")
def test_jaeger_get_service_dependencies_live_status_error(mock_http_get):
    jaeger_tools.jaeger_configured = True
    
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_http_get.return_value = mock_response
    
    res = jaeger_tools.get_service_dependencies.invoke({"service_name": "backend"})
    assert "Error querying Jaeger dependencies: Status code 500" in res

@patch("tools.jaeger_tools.httpx.get")
def test_jaeger_get_service_dependencies_live_exception(mock_http_get):
    jaeger_tools.jaeger_configured = True
    mock_http_get.side_effect = Exception("Jaeger offline")
    
    res = jaeger_tools.get_service_dependencies.invoke({"service_name": "backend"})
    assert "Error querying Jaeger: Jaeger offline" in res
