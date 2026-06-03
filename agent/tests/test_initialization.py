import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# A helper to reset flags in-place to avoid reload network timeouts
def restore_modules():

    if "tools.k8s_tools" in sys.modules:
        sys.modules["tools.k8s_tools"].k8s_configured = False
    if "tools.github_tools" in sys.modules:
        sys.modules["tools.github_tools"].github_configured = False
    if "tools.prometheus_tools" in sys.modules:
        sys.modules["tools.prometheus_tools"].prom_configured = False
    if "tools.jaeger_tools" in sys.modules:
        sys.modules["tools.jaeger_tools"].jaeger_configured = False


@pytest.fixture(autouse=True)
def clean_reload_fixture():
    yield
    restore_modules()


# Test tracing module OTel connection failure
@patch("opentelemetry.sdk.trace.TracerProvider.add_span_processor")
def test_tracing_otel_connection_failure(mock_add_span_processor):
    mock_add_span_processor.side_effect = Exception("OTel connection failed")
    import tracing

    importlib.reload(tracing)
    from opentelemetry import trace

    assert trace.get_tracer_provider() is not None


# Test k8s_tools in-cluster config success
@patch("kubernetes.config.load_incluster_config")
@patch("kubernetes.config.load_kube_config")
def test_k8s_in_cluster_success(mock_load_kube, mock_load_in_cluster):
    mock_load_in_cluster.return_value = None  # succeeds
    from tools import k8s_tools

    importlib.reload(k8s_tools)
    assert k8s_tools.k8s_configured is True
    mock_load_in_cluster.assert_called()
    mock_load_kube.assert_not_called()


# Test k8s_tools external kubeconfig success
@patch("kubernetes.config.load_incluster_config")
@patch("kubernetes.config.load_kube_config")
def test_k8s_external_success(mock_load_kube, mock_load_in_cluster):
    mock_load_in_cluster.side_effect = Exception("Not in cluster")
    mock_load_kube.return_value = None  # succeeds
    from tools import k8s_tools

    importlib.reload(k8s_tools)
    assert k8s_tools.k8s_configured is True
    mock_load_in_cluster.assert_called()
    mock_load_kube.assert_called()


# Test github_tools successfully configured client
@patch("github.Github")
def test_github_tools_configured_success(mock_github_class, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake_token")
    mock_g_instance = MagicMock()
    mock_g_instance.get_user.return_value.login = "test_user"
    mock_github_class.return_value = mock_g_instance

    from tools import github_tools

    importlib.reload(github_tools)
    assert github_tools.github_configured is True


# Test github_tools failed to configure (exception)
@patch("github.Github")
def test_github_tools_exception(mock_github_class, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake_token")
    mock_github_class.side_effect = Exception("API rate limit or invalid token")

    from tools import github_tools

    importlib.reload(github_tools)
    assert github_tools.github_configured is False


# Test prometheus_tools successful connection check
@patch("prometheus_api_client.PrometheusConnect")
def test_prometheus_tools_success(mock_prom_class):
    mock_prom_instance = MagicMock()
    mock_prom_instance.check_prometheus_connection.return_value = True
    mock_prom_class.return_value = mock_prom_instance

    from tools import prometheus_tools

    importlib.reload(prometheus_tools)
    assert prometheus_tools.prom_configured is True


# Test prometheus_tools failed connection check
@patch("prometheus_api_client.PrometheusConnect")
def test_prometheus_tools_fail(mock_prom_class):
    mock_prom_instance = MagicMock()
    mock_prom_instance.check_prometheus_connection.return_value = False
    mock_prom_class.return_value = mock_prom_instance

    from tools import prometheus_tools

    importlib.reload(prometheus_tools)
    assert prometheus_tools.prom_configured is False


# Test jaeger_tools successful connection
@patch("httpx.get")
def test_jaeger_tools_success(mock_get):
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_get.return_value = mock_res

    from tools import jaeger_tools

    importlib.reload(jaeger_tools)
    assert jaeger_tools.jaeger_configured is True
