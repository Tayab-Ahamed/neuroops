import os
import structlog
from pydantic import BaseModel
from kubernetes import config as k8s_config
from github import Github

logger = structlog.get_logger()

class ActionResult(BaseModel):
    success: bool
    action_taken: str
    duration_seconds: float

# Initialize Kubernetes client configuration
k8s_configured = False
try:
    try:
        k8s_config.load_incluster_config()
        k8s_configured = True
        logger.info("remediator: Loaded in-cluster Kubernetes configuration")
    except Exception:
        k8s_config.load_kube_config()
        k8s_configured = True
        logger.info("remediator: Loaded external kubeconfig configuration")
except Exception as e:
    logger.warning("remediator: Kubernetes client is not configured, running K8s actions in mock mode", error=str(e))

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
        logger.warning("remediator: GITHUB_TOKEN is not configured, running GitHub actions in mock mode")
except Exception as e:
    logger.warning("remediator: Failed to configure GitHub client, running in mock mode", error=str(e))
