import os
import time
from typing import Any

import structlog
from github import Github, GithubException
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException
from pydantic import BaseModel

logger = structlog.get_logger()


class ActionResult(BaseModel):
    success: bool
    action_taken: str
    duration_seconds: float
    metadata: dict[str, Any] | None = None


def get_action_timeout_seconds() -> float:
    """Returns the configured action wait timeout."""
    raw_timeout = os.getenv("ACTION_TIMEOUT_SECONDS", "90")
    try:
        return float(raw_timeout)
    except ValueError:
        logger.warning(
            "Invalid ACTION_TIMEOUT_SECONDS value, using default",
            value=raw_timeout,
            default=90.0,
        )
        return 90.0


def is_not_found(exc: ApiException) -> bool:
    return exc.status == 404


def skipped_not_found(start_time: float) -> ActionResult:
    return ActionResult(
        success=False,
        action_taken="skipped — resource not found",
        duration_seconds=time.time() - start_time,
    )


def timeout_result(start_time: float) -> ActionResult:
    return ActionResult(
        success=False,
        action_taken="verification timed out",
        duration_seconds=time.time() - start_time,
    )


def get_k8s_context() -> str | None:
    """Returns the configured Kubernetes context name, or None for current-context."""
    return os.getenv("KUBECONFIG_CONTEXT") or None


def get_k8s_api_client() -> k8s_client.CoreV1Api:
    """Returns a CoreV1Api client for the configured cluster context."""
    context = get_k8s_context()
    if context:
        api_client = k8s_config.new_client_from_config(context=context)
        return k8s_client.CoreV1Api(api_client=api_client)
    return k8s_client.CoreV1Api()


def get_k8s_apps_client() -> k8s_client.AppsV1Api:
    """Returns an AppsV1Api client for the configured cluster context."""
    context = get_k8s_context()
    if context:
        api_client = k8s_config.new_client_from_config(context=context)
        return k8s_client.AppsV1Api(api_client=api_client)
    return k8s_client.AppsV1Api()


# Initialize Kubernetes client configuration
k8s_configured = False
_k8s_context = get_k8s_context()

try:
    try:
        k8s_config.load_incluster_config()
        k8s_configured = True
        logger.info("remediator: Loaded in-cluster Kubernetes configuration")
    except ConfigException as exc:
        logger.warning(
            "remediator: In-cluster Kubernetes configuration unavailable",
            error=str(exc),
        )
        k8s_config.load_kube_config(context=_k8s_context)
        k8s_configured = True
        logger.info(
            "remediator: Loaded external kubeconfig configuration",
            context=_k8s_context or "(current-context)",
        )
except Exception as e:
    logger.warning(
        "remediator: Kubernetes client is not configured, running K8s actions in mock mode",
        error=str(e),
    )

# Setup GitHub client configuration
github_configured = False
github_token = os.getenv("GITHUB_TOKEN")
try:
    if github_token:
        g = Github(github_token)
        # Touch API to verify config
        g.get_user().login
        github_configured = True
        logger.info("remediator: Successfully configured PyGithub client")
    else:
        logger.warning(
            "remediator: GITHUB_TOKEN is not configured, running GitHub actions in mock mode"
        )
except Exception as e:
    logger.warning(
        "remediator: Failed to configure GitHub client, running in mock mode", error=str(e)
    )
