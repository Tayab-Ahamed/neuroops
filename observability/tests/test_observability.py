"""Unit tests for the observability layer — dashboards, OTel config, and replay utilities."""

import json
import os


def _obs_path(*parts) -> str:
    """Resolve a path relative to the observability/ directory."""
    base = os.path.join(os.path.dirname(__file__), "..")
    return os.path.normpath(os.path.join(base, *parts))


def test_replay_module_file_exists():
    """replay.py module file exists in observability/."""
    assert os.path.isfile(_obs_path("replay.py")), "observability/replay.py not found"


def test_dashboard_module_file_exists():
    """dashboard.py module file exists in observability/."""
    assert os.path.isfile(_obs_path("dashboard.py")), "observability/dashboard.py not found"


def test_grafana_incident_dashboard_json_exists():
    """Grafana incident dashboard JSON file exists."""
    path = _obs_path("dashboards", "neuroops-incident.json")
    assert os.path.isfile(path), f"Missing: {path}"


def test_grafana_overview_dashboard_json_exists():
    """Grafana overview dashboard JSON file exists."""
    path = _obs_path("dashboards", "neuroops-overview.json")
    assert os.path.isfile(path), f"Missing: {path}"


def test_otel_collector_config_exists():
    """OTel collector config YAML file exists."""
    path = _obs_path("collector", "otel-collector-config.yaml")
    assert os.path.isfile(path), f"Missing: {path}"


def test_grafana_dashboard_provisioning_yaml_exists():
    """Grafana dashboard provisioning YAML exists."""
    path = _obs_path("grafana", "provisioning", "dashboards", "dashboards.yaml")
    assert os.path.isfile(path), f"Missing: {path}"


def test_grafana_datasources_provisioning_yaml_exists():
    """Grafana datasources provisioning YAML exists."""
    path = _obs_path("grafana", "provisioning", "datasources", "datasources.yaml")
    assert os.path.isfile(path), f"Missing: {path}"


def test_grafana_incident_dashboard_is_valid_json():
    """Grafana incident dashboard JSON is parseable and has expected top-level keys."""
    path = _obs_path("dashboards", "neuroops-incident.json")
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Dashboard JSON root must be an object"
    # Either panels or title must be present in a valid Grafana dashboard
    assert "panels" in data or "title" in data, "Dashboard JSON missing 'panels' or 'title'"


def test_grafana_overview_dashboard_is_valid_json():
    """Grafana overview dashboard JSON is parseable and has expected top-level keys."""
    path = _obs_path("dashboards", "neuroops-overview.json")
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Dashboard JSON root must be an object"
    assert "panels" in data or "title" in data, "Dashboard JSON missing 'panels' or 'title'"


def test_dashboards_provisioning_references_correct_path():
    """dashboards.yaml provisioning config points to the correct Grafana dashboard directory."""
    path = _obs_path("grafana", "provisioning", "dashboards", "dashboards.yaml")
    with open(path) as f:
        content = f.read()
    # The provisioning path should reference the mounted dashboard directory
    assert (
        "/var/lib/grafana/dashboards" in content
    ), "dashboards.yaml should point to /var/lib/grafana/dashboards"


def test_datasources_provisioning_references_prometheus():
    """datasources.yaml provisioning config includes a Prometheus datasource."""
    path = _obs_path("grafana", "provisioning", "datasources", "datasources.yaml")
    with open(path) as f:
        content = f.read()
    assert "prometheus" in content.lower(), "datasources.yaml must define a Prometheus datasource"
    assert "jaeger" in content.lower(), "datasources.yaml must define a Jaeger datasource"
