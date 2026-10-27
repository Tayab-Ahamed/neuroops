"""Transport exceptions need not expose Kubernetes ApiException attributes."""
import importlib

import pytest


@pytest.mark.parametrize("module,function,args", [
    ("restart_pod", "restart_pod", ("default", "backend-pod")),
    ("rollback_deploy", "rollback_deployment", ("default", "backend")),
    ("scale_replicas", "scale_deployment", ("default", "backend", 3)),
    ("patch_configmap", "patch_configmap", ("default", "backend-config", {"data": {"key": "value"}})),
])
def test_kubernetes_transport_errors_return_controlled_failure(module, function, args, monkeypatch):
    action = importlib.import_module("remediator.actions." + module)
    monkeypatch.setattr(action, "k8s_configured", True)

    def unavailable(*args, **kwargs):
        raise ConnectionError("cluster transport unavailable")

    monkeypatch.setattr(action.client, "CoreV1Api", unavailable)
    monkeypatch.setattr(action.client, "AppsV1Api", unavailable)
    result = getattr(action, function)(*args)
    assert result.success is False
    assert "cluster transport unavailable" in result.action_taken


def test_not_found_classification_accepts_generic_errors():
    from remediator.actions import is_not_found

    assert not is_not_found(ConnectionError("unavailable"))
