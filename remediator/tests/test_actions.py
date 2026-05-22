import pytest
import os
import time
from unittest.mock import patch, MagicMock
from remediator.actions.restart_pod import restart_pod
from remediator.actions.rollback_deploy import rollback_deployment
from remediator.actions.scale_replicas import scale_deployment
from remediator.actions.patch_configmap import patch_configmap
from remediator.actions.open_github_pr import open_pr

# ==========================================
# 1. restart_pod Action Tests
# ==========================================

def test_restart_pod_mock_mode():
    with patch("remediator.actions.restart_pod.k8s_configured", False):
        res = restart_pod("default", "backend-pod")
        assert res.success is True
        assert "Mock: Successfully restarted pod" in res.action_taken

def test_restart_pod_real_success():
    mock_v1 = MagicMock()
    # Read pod metadata (returns labels)
    mock_pod = MagicMock()
    mock_pod.metadata.labels = {"app": "backend", "pod-template-hash": "123"}
    mock_v1.read_namespaced_pod.return_value = mock_pod
    
    # List namespaced pods (returns Running/Ready pods)
    mock_container_status = MagicMock()
    mock_container_status.ready = True
    mock_pod_item = MagicMock()
    mock_pod_item.metadata.name = "backend-new-pod"
    mock_pod_item.status.phase = "Running"
    mock_pod_item.status.container_statuses = [mock_container_status]
    
    mock_pods_list = MagicMock()
    mock_pods_list.items = [mock_pod_item]
    mock_v1.list_namespaced_pod.return_value = mock_pods_list

    with patch("remediator.actions.restart_pod.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1), \
         patch("time.sleep"):
        res = restart_pod("default", "backend-pod")
        assert res.success is True
        assert "Successfully restarted pod" in res.action_taken
        assert mock_v1.delete_namespaced_pod.called

def test_restart_pod_metadata_failure_fallback():
    mock_v1 = MagicMock()
    # Read pod raises exception (metadata fail)
    mock_v1.read_namespaced_pod.side_effect = Exception("failed to read")
    
    # List namespaced pods returns a running/ready pod matching app=backend
    mock_container_status = MagicMock()
    mock_container_status.ready = True
    mock_pod_item = MagicMock()
    mock_pod_item.metadata.name = "backend-new-pod"
    mock_pod_item.status.phase = "Running"
    mock_pod_item.status.container_statuses = [mock_container_status]
    
    mock_pods_list = MagicMock()
    mock_pods_list.items = [mock_pod_item]
    mock_v1.list_namespaced_pod.return_value = mock_pods_list

    with patch("remediator.actions.restart_pod.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1), \
         patch("time.sleep"):
        res = restart_pod("default", "backend-pod")
        assert res.success is True
        assert mock_v1.delete_namespaced_pod.called

def test_restart_pod_timeout():
    mock_v1 = MagicMock()
    mock_pod = MagicMock()
    mock_pod.metadata.labels = {"app": "backend"}
    mock_v1.read_namespaced_pod.return_value = mock_pod
    
    # List namespaced pods returns a non-ready pod
    mock_container_status = MagicMock()
    mock_container_status.ready = False
    mock_pod_item = MagicMock()
    mock_pod_item.metadata.name = "backend-new-pod"
    mock_pod_item.status.phase = "Running"
    mock_pod_item.status.container_statuses = [mock_container_status]
    
    mock_pods_list = MagicMock()
    mock_pods_list.items = [mock_pod_item]
    mock_v1.list_namespaced_pod.return_value = mock_pods_list

    with patch("remediator.actions.restart_pod.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1), \
         patch("time.sleep"), \
         patch("time.time", side_effect=[0, 10, 20, 30, 40, 50, 60, 70, 80, 200]):
        res = restart_pod("default", "backend-pod")
        assert res.success is False
        assert "verification timed out" in res.action_taken

def test_restart_pod_exception():
    mock_v1 = MagicMock()
    mock_v1.delete_namespaced_pod.side_effect = Exception("General K8s Error")

    with patch("remediator.actions.restart_pod.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
        res = restart_pod("default", "backend-pod")
        assert res.success is False
        assert "Failed to restart pod" in res.action_taken

# ==========================================
# 2. rollback_deployment Action Tests
# ==========================================

def test_rollback_deployment_mock_mode():
    with patch("remediator.actions.rollback_deploy.k8s_configured", False):
        res = rollback_deployment("default", "backend")
        assert res.success is True
        assert "Mock: Rolled back deployment" in res.action_taken

def test_rollback_deployment_success():
    mock_apps = MagicMock()
    
    # Mock active deployment metadata & spec selector
    mock_dep = MagicMock()
    mock_dep.metadata.annotations = {"deployment.kubernetes.io/revision": "3"}
    mock_dep.spec.selector.match_labels = {"app": "backend"}
    mock_apps.read_namespaced_deployment.return_value = mock_dep
    
    # Mock ReplicaSets revision history
    rs1 = MagicMock()
    rs1.metadata.annotations = {"deployment.kubernetes.io/revision": "1"}
    rs2 = MagicMock()
    rs2.metadata.annotations = {"deployment.kubernetes.io/revision": "2"}
    rs2.metadata.name = "backend-rs2"
    rs2.spec.template.spec.containers = [MagicMock(name="backend", image="backend:v1")]
    rs3 = MagicMock()
    rs3.metadata.annotations = {"deployment.kubernetes.io/revision": "3"}
    
    mock_rs_list = MagicMock()
    mock_rs_list.items = [rs1, rs2, rs3]
    mock_apps.list_namespaced_replica_set.return_value = mock_rs_list

    # Mock status check for complete rollout
    mock_status_dep = MagicMock()
    mock_status_dep.metadata.generation = 12
    mock_status_dep.status.observed_generation = 12
    mock_status_dep.spec.replicas = 2
    mock_status_dep.status.updated_replicas = 2
    mock_status_dep.status.ready_replicas = 2
    mock_status_dep.status.available_replicas = 2
    
    # Trigger read deployment status check
    mock_apps.read_namespaced_deployment.side_effect = [mock_dep, mock_status_dep]

    with patch("remediator.actions.rollback_deploy.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps), \
         patch("time.sleep"):
        res = rollback_deployment("default", "backend")
        assert res.success is True
        assert "Successfully rolled back deployment" in res.action_taken

def test_rollback_deployment_no_history():
    mock_apps = MagicMock()
    mock_dep = MagicMock()
    mock_dep.metadata.annotations = {}
    mock_dep.spec.selector.match_labels = {"app": "backend"}
    mock_apps.read_namespaced_deployment.return_value = mock_dep
    
    # Single ReplicaSet, no previous history
    rs3 = MagicMock()
    rs3.metadata.annotations = {"deployment.kubernetes.io/revision": "3"}
    mock_rs_list = MagicMock()
    mock_rs_list.items = [rs3]
    mock_apps.list_namespaced_replica_set.return_value = mock_rs_list

    with patch("remediator.actions.rollback_deploy.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps):
        res = rollback_deployment("default", "backend")
        assert res.success is False
        assert "has no previous revision history" in res.action_taken

def test_rollback_deployment_fallback_revisions():
    mock_apps = MagicMock()
    mock_dep = MagicMock()
    mock_dep.metadata.annotations = {"deployment.kubernetes.io/revision": "1"} # current is 1 (no lower revision available)
    mock_dep.spec.selector.match_labels = {"app": "backend"}
    mock_apps.read_namespaced_deployment.return_value = mock_dep
    
    rs1 = MagicMock()
    rs1.metadata.annotations = {"deployment.kubernetes.io/revision": "1"}
    rs1.spec.template.spec.containers = [MagicMock(name="backend", image="backend:v1")]
    rs2 = MagicMock()
    rs2.metadata.annotations = {"deployment.kubernetes.io/revision": "2"}
    mock_rs_list = MagicMock()
    mock_rs_list.items = [rs1, rs2]
    mock_apps.list_namespaced_replica_set.return_value = mock_rs_list
    
    # Trigger exception on patch to check exception flow
    mock_apps.patch_namespaced_deployment.side_effect = Exception("failed to patch")

    with patch("remediator.actions.rollback_deploy.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps):
        res = rollback_deployment("default", "backend")
        assert res.success is False
        assert "Failed to rollback deployment" in res.action_taken

def test_rollback_deployment_timeout():
    mock_apps = MagicMock()
    mock_dep = MagicMock()
    mock_dep.metadata.annotations = {"deployment.kubernetes.io/revision": "3"}
    mock_dep.spec.selector.match_labels = {"app": "backend"}
    mock_apps.read_namespaced_deployment.return_value = mock_dep
    
    rs2 = MagicMock()
    rs2.metadata.annotations = {"deployment.kubernetes.io/revision": "2"}
    rs2.spec.template.spec.containers = [MagicMock(name="backend", image="backend:v1")]
    rs3 = MagicMock()
    rs3.metadata.annotations = {"deployment.kubernetes.io/revision": "3"}
    mock_rs_list = MagicMock()
    mock_rs_list.items = [rs2, rs3]
    mock_apps.list_namespaced_replica_set.return_value = mock_rs_list

    # Status check remains pending/generation mismatched
    mock_status_dep = MagicMock()
    mock_status_dep.metadata.generation = 12
    mock_status_dep.status.observed_generation = 11  # observed < generation
    mock_status_dep.spec.replicas = 2
    mock_status_dep.status.updated_replicas = 1
    
    mock_apps.read_namespaced_deployment.side_effect = [mock_dep, mock_status_dep]

    with patch("remediator.actions.rollback_deploy.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps), \
         patch("time.sleep"), \
         patch("time.time", side_effect=[0, 10, 20, 30, 40, 50, 60, 70, 80, 200]):
        res = rollback_deployment("default", "backend")
        assert res.success is False
        assert "status verification timed out" in res.action_taken

# ==========================================
# 3. scale_replicas Action Tests
# ==========================================

def test_scale_deployment_mock_mode():
    with patch("remediator.actions.scale_replicas.k8s_configured", False):
        res = scale_deployment("default", "backend", 4)
        assert res.success is True
        assert "Mock: Scaled deployment" in res.action_taken

def test_scale_deployment_idempotency_success():
    mock_apps = MagicMock()
    mock_dep = MagicMock()
    mock_dep.spec.replicas = 3 # Current replica is already 3
    mock_apps.read_namespaced_deployment.return_value = mock_dep

    # Verification checks
    mock_status_dep = MagicMock()
    mock_status_dep.status.ready_replicas = 3
    mock_status_dep.status.updated_replicas = 3
    mock_apps.read_namespaced_deployment.side_effect = [mock_dep, mock_status_dep]

    with patch("remediator.actions.scale_replicas.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps), \
         patch("time.sleep"):
        res = scale_deployment("default", "backend", 3)
        assert res.success is True
        assert "Successfully scaled deployment" in res.action_taken
        assert not mock_apps.patch_namespaced_deployment.called

def test_scale_deployment_scaling_success():
    mock_apps = MagicMock()
    mock_dep = MagicMock()
    mock_dep.spec.replicas = 1 # Current replica is 1, target is 3
    mock_apps.read_namespaced_deployment.return_value = mock_dep

    # Verification checks
    mock_status_dep = MagicMock()
    mock_status_dep.status.ready_replicas = 3
    mock_status_dep.status.updated_replicas = 3
    mock_apps.read_namespaced_deployment.side_effect = [mock_dep, mock_status_dep]

    with patch("remediator.actions.scale_replicas.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps), \
         patch("time.sleep"):
        res = scale_deployment("default", "backend", 3)
        assert res.success is True
        assert mock_apps.patch_namespaced_deployment.called

def test_scale_deployment_scale_to_zero():
    mock_apps = MagicMock()
    mock_dep = MagicMock()
    mock_dep.spec.replicas = 3
    mock_apps.read_namespaced_deployment.return_value = mock_dep

    # Verification checks (checking replica counts fall to 0)
    mock_status_dep = MagicMock()
    mock_status_dep.status.replicas = 0
    mock_apps.read_namespaced_deployment.side_effect = [mock_dep, mock_status_dep]

    with patch("remediator.actions.scale_replicas.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps), \
         patch("time.sleep"):
        res = scale_deployment("default", "backend", 0)
        assert res.success is True
        assert mock_apps.patch_namespaced_deployment.called

def test_scale_deployment_timeout():
    mock_apps = MagicMock()
    mock_dep = MagicMock()
    mock_dep.spec.replicas = 1
    mock_apps.read_namespaced_deployment.return_value = mock_dep

    # Verification checks remain stuck at ready = 1
    mock_status_dep = MagicMock()
    mock_status_dep.status.ready_replicas = 1
    mock_status_dep.status.updated_replicas = 3
    mock_apps.read_namespaced_deployment.side_effect = [mock_dep, mock_status_dep]

    with patch("remediator.actions.scale_replicas.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps), \
         patch("time.sleep"), \
         patch("time.time", side_effect=[0, 10, 20, 30, 40, 50, 60, 70, 80, 200]):
        res = scale_deployment("default", "backend", 3)
        assert res.success is False
        assert "verification timed out" in res.action_taken

def test_scale_deployment_exception():
    mock_apps = MagicMock()
    mock_apps.read_namespaced_deployment.side_effect = Exception("K8s API Saturation")

    with patch("remediator.actions.scale_replicas.k8s_configured", True), \
         patch("kubernetes.client.AppsV1Api", return_value=mock_apps):
        res = scale_deployment("default", "backend", 3)
        assert res.success is False
        assert "Failed to scale deployment" in res.action_taken

# ==========================================
# 4. patch_configmap Action Tests
# ==========================================

def test_patch_configmap_mock_mode():
    with patch("remediator.actions.patch_configmap.k8s_configured", False):
        res = patch_configmap("default", "backend-cm", {"data": {"A": "B"}})
        assert res.success is True
        assert "Mock: Patched ConfigMap" in res.action_taken

def test_patch_configmap_success():
    mock_v1 = MagicMock()

    with patch("remediator.actions.patch_configmap.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
        res = patch_configmap("default", "backend-cm", {"data": {"A": "B"}})
        assert res.success is True
        assert mock_v1.patch_namespaced_config_map.called

def test_patch_configmap_failure():
    mock_v1 = MagicMock()
    mock_v1.patch_namespaced_config_map.side_effect = Exception("Resource Lock Error")

    with patch("remediator.actions.patch_configmap.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1):
        res = patch_configmap("default", "backend-cm", {"data": {"A": "B"}})
        assert res.success is False
        assert "Failed to patch ConfigMap" in res.action_taken

# ==========================================
# 5. open_github_pr Action Tests
# ==========================================

def test_open_pr_mock_mode():
    with patch("remediator.actions.open_github_pr.github_configured", False):
        res = open_pr("repo", "title", "body", "branch", {"file.py": "content"})
        assert res.success is True
        assert "Mock: Opened Pull Request" in res.action_taken

def test_open_pr_success():
    mock_github = MagicMock()
    mock_repo = MagicMock()
    mock_github.get_repo.return_value = mock_repo
    
    # Mock default branch & branch ref creation
    mock_repo.default_branch = "main"
    mock_repo.get_branch.return_value.commit.sha = "root_sha"
    
    # Mock contents check (throws exception for file 1 - creates, returns success for file 2 - updates)
    mock_contents = MagicMock()
    mock_contents.sha = "file_sha"
    mock_repo.get_contents.side_effect = [Exception("404"), mock_contents]
    
    # Mock Pull Request
    mock_pr = MagicMock()
    mock_pr.number = 42
    mock_pr.title = "remediation: config patch"
    mock_pr.html_url = "https://github.com/pr/42"
    mock_repo.create_pull.return_value = mock_pr

    with patch("remediator.actions.open_github_pr.github_configured", True), \
         patch("remediator.actions.open_github_pr.Github", return_value=mock_github):
        res = open_pr(
            "neuroops-project/neuroops", 
            "title", 
            "body", 
            "branch", 
            {"newfile.py": "content", "oldfile.py": "updated"}
        )
        assert res.success is True
        assert "Successfully opened GitHub Pull Request #42" in res.action_taken

def test_open_pr_failure():
    mock_github = MagicMock()
    mock_github.get_repo.side_effect = Exception("Repository Forbidden")

    with patch("remediator.actions.open_github_pr.github_configured", True), \
         patch("remediator.actions.open_github_pr.Github", return_value=mock_github):
        res = open_pr("neuroops-project/neuroops", "title", "body", "branch", {})
        assert res.success is False
        assert "Failed to open GitHub Pull Request" in res.action_taken

# ==========================================
# 6. Additional Coverage & Reload Tests
# ==========================================

import importlib
import sys

def test_module_initialization_incluster_success():
    mock_k8s_config = MagicMock()
    mock_k8s_config.load_incluster_config.return_value = None
    
    mock_github = MagicMock()
    mock_github.return_value.get_user.return_value.login = "neuroops-bot"
    
    with patch("kubernetes.config.load_incluster_config", mock_k8s_config.load_incluster_config), \
         patch("kubernetes.config.load_kube_config", side_effect=Exception("no kube config")), \
         patch("github.Github", mock_github), \
         patch.dict(os.environ, {"GITHUB_TOKEN": "some_token"}):
        import remediator.actions
        importlib.reload(remediator.actions)
        assert remediator.actions.k8s_configured is True
        assert remediator.actions.github_configured is True

def test_module_initialization_kubeconfig_success():
    mock_k8s_config = MagicMock()
    mock_k8s_config.load_incluster_config.side_effect = Exception("not in cluster")
    mock_k8s_config.load_kube_config.return_value = None
    
    mock_github = MagicMock()
    mock_github.return_value.get_user.side_effect = Exception("Bad credentials")
    
    with patch("kubernetes.config.load_incluster_config", mock_k8s_config.load_incluster_config), \
         patch("kubernetes.config.load_kube_config", mock_k8s_config.load_kube_config), \
         patch("github.Github", mock_github), \
         patch.dict(os.environ, {"GITHUB_TOKEN": "some_token"}):
        import remediator.actions
        importlib.reload(remediator.actions)
        assert remediator.actions.k8s_configured is True
        assert remediator.actions.github_configured is False

def test_open_pr_branch_already_exists():
    mock_github = MagicMock()
    mock_repo = MagicMock()
    mock_github.get_repo.return_value = mock_repo
    mock_repo.default_branch = "main"
    mock_repo.get_branch.return_value.commit.sha = "root_sha"
    
    mock_repo.create_git_ref.side_effect = Exception("Reference already exists")
    
    mock_contents = MagicMock()
    mock_contents.sha = "file_sha"
    mock_repo.get_contents.return_value = mock_contents
    
    mock_pr = MagicMock()
    mock_pr.number = 42
    mock_pr.title = "remediation: config patch"
    mock_pr.html_url = "https://github.com/pr/42"
    mock_repo.create_pull.return_value = mock_pr

    with patch("remediator.actions.open_github_pr.github_configured", True), \
         patch("remediator.actions.open_github_pr.Github", return_value=mock_github):
        res = open_pr(
            "neuroops-project/neuroops", 
            "title", 
            "body", 
            "branch", 
            {"file.py": "content"}
        )
        assert res.success is True
        assert mock_repo.create_git_ref.called

def test_restart_pod_empty_pods_list_first_then_success():
    mock_v1 = MagicMock()
    mock_pod = MagicMock()
    mock_pod.metadata.labels = {"app": "backend"}
    mock_v1.read_namespaced_pod.return_value = mock_pod
    
    mock_container_status = MagicMock()
    mock_container_status.ready = True
    mock_pod_item = MagicMock()
    mock_pod_item.metadata.name = "backend-new-pod"
    mock_pod_item.status.phase = "Running"
    mock_pod_item.status.container_statuses = [mock_container_status]
    
    mock_pods_list_empty = MagicMock()
    mock_pods_list_empty.items = []
    mock_pods_list_ok = MagicMock()
    mock_pods_list_ok.items = [mock_pod_item]
    
    mock_v1.list_namespaced_pod.side_effect = [mock_pods_list_empty, mock_pods_list_ok]

    with patch("remediator.actions.restart_pod.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1), \
         patch("time.sleep"):
        res = restart_pod("default", "backend-pod")
        assert res.success is True

def test_restart_pod_no_container_statuses():
    mock_v1 = MagicMock()
    mock_pod = MagicMock()
    mock_pod.metadata.labels = {"app": "backend"}
    mock_v1.read_namespaced_pod.return_value = mock_pod
    
    mock_pod_item_no_status = MagicMock()
    mock_pod_item_no_status.metadata.name = "backend-new-pod"
    mock_pod_item_no_status.status.phase = "Running"
    mock_pod_item_no_status.status.container_statuses = None
    
    mock_container_status = MagicMock()
    mock_container_status.ready = True
    mock_pod_item_ok = MagicMock()
    mock_pod_item_ok.metadata.name = "backend-new-pod"
    mock_pod_item_ok.status.phase = "Running"
    mock_pod_item_ok.status.container_statuses = [mock_container_status]
    
    mock_list_1 = MagicMock()
    mock_list_1.items = [mock_pod_item_no_status]
    mock_list_2 = MagicMock()
    mock_list_2.items = [mock_pod_item_ok]
    
    mock_v1.list_namespaced_pod.side_effect = [mock_list_1, mock_list_2]

    with patch("remediator.actions.restart_pod.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1), \
         patch("time.sleep"):
        res = restart_pod("default", "backend-pod")
        assert res.success is True

def test_restart_pod_list_exception_in_loop():
    mock_v1 = MagicMock()
    mock_pod = MagicMock()
    mock_pod.metadata.labels = {"app": "backend"}
    mock_v1.read_namespaced_pod.return_value = mock_pod
    
    mock_container_status = MagicMock()
    mock_container_status.ready = True
    mock_pod_item = MagicMock()
    mock_pod_item.metadata.name = "backend-new-pod"
    mock_pod_item.status.phase = "Running"
    mock_pod_item.status.container_statuses = [mock_container_status]
    
    mock_list_ok = MagicMock()
    mock_list_ok.items = [mock_pod_item]
    
    mock_v1.list_namespaced_pod.side_effect = [Exception("Temporary API Error"), mock_list_ok]

    with patch("remediator.actions.restart_pod.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1), \
         patch("time.sleep"):
        res = restart_pod("default", "backend-pod")
        assert res.success is True

def test_restart_pod_timeout_phase_pending():
    mock_v1 = MagicMock()
    mock_pod = MagicMock()
    mock_pod.metadata.labels = {"app": "backend"}
    mock_v1.read_namespaced_pod.return_value = mock_pod
    
    mock_pod_item = MagicMock()
    mock_pod_item.metadata.name = "backend-new-pod"
    mock_pod_item.status.phase = "Pending"
    mock_pod_item.status.container_statuses = []
    
    mock_pods_list = MagicMock()
    mock_pods_list.items = [mock_pod_item]
    mock_v1.list_namespaced_pod.return_value = mock_pods_list

    with patch("remediator.actions.restart_pod.k8s_configured", True), \
         patch("kubernetes.client.CoreV1Api", return_value=mock_v1), \
         patch("time.sleep"), \
         patch("time.time", side_effect=[0, 10, 20, 30, 40, 50, 60, 70, 80, 200]):
        res = restart_pod("default", "backend-pod")
        assert res.success is False
