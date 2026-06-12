import os
import time
from typing import Any

import structlog
from github import Github, GithubException
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
        action_taken="timeout waiting for ready state",
        duration_seconds=time.time() - start_time,
    )


# Initialize Kubernetes client configuration
k8s_configured = False
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
        k8s_config.load_kube_config()
        k8s_configured = True
        logger.info("remediator: Loaded external kubeconfig configuration")
except ConfigException as e:
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
except GithubException as e:
    logger.warning(
        "remediator: Failed to configure GitHub client, running in mock mode", error=str(e)
    )
