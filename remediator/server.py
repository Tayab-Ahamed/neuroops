import os
from typing import List, Dict, Any, Optional, Union
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import structlog
from kubernetes import client

# Import actions, verifier, and human loop
from remediator.actions import ActionResult, k8s_configured, logger
from remediator.actions.restart_pod import restart_pod
from remediator.actions.rollback_deploy import rollback_deployment
from remediator.actions.scale_replicas import scale_deployment
from remediator.actions.patch_configmap import patch_configmap
from remediator.actions.open_github_pr import open_pr
from remediator.human_loop import prompt_human
from remediator.verifier import verify_resolution

app = FastAPI(title="NeuroOps Remediation Engine API", version="1.0.0")

# Global history registry of actions taken
actions_history: List[ActionResult] = []

class AlertModel(BaseModel):
    id: str
    service: str
    severity: str
    timestamp: float
    metric_snapshot: Dict[str, float]
    anomaly_score: float

class RemediationRequest(BaseModel):
    incident_id: str
    hypothesis: str
    confidence: float
    recommended_action: str
    requires_human_approval: bool
    reasoning: str
    
    # Optional extensions for precise orchestrator control
    alert: Optional[Union[AlertModel, Dict[str, Any]]] = None
    namespace: Optional[str] = "neuroops-demo"
    pod_name: Optional[str] = None
    deployment_name: Optional[str] = None
    replicas: Optional[int] = None
    patch: Optional[Dict[str, Any]] = None
    repo: Optional[str] = None

def extract_service_name(hypothesis: str, reasoning: str) -> str:
    """Helper to parse affected service name from hypothesis/reasoning text."""
    combined = (hypothesis + " " + reasoning).lower()
    if "database-stub" in combined:
        return "database-stub"
    elif "frontend" in combined:
        return "frontend"
    elif "backend" in combined:
        return "backend"
    return "backend" # Default fallback

@app.post("/remediate", response_model=ActionResult)
async def remediate(request: RemediationRequest):
    """
    Executes the recommended remediation action based on the RCA hypothesis.
    Invokes human-in-the-loop CLI prompts for actions requiring approval.
    """
    logger.info("Received remediation request", incident_id=request.incident_id, action=request.recommended_action)
    
    # 1. P2 Check / Human approval loop gate
    if request.requires_human_approval:
        logger.info("Action requires human operator approval, invoking CLI loop", incident_id=request.incident_id)
        # Note: prompt_human runs synchronously to wait for operator input (or timeout)
        approved = prompt_human(request, request.recommended_action)
        if not approved:
            result = ActionResult(
                success=False,
                action_taken=f"Rejected: Action '{request.recommended_action}' rejected by human operator or timed out.",
                duration_seconds=0.0
            )
            actions_history.append(result)
            return result

    # 2. Extract service and configurations
    service = extract_service_name(request.hypothesis, request.reasoning)
    namespace = request.namespace or "neuroops-demo"
    action_type = request.recommended_action.lower()
    
    logger.info("Parsed remediation target details", service=service, namespace=namespace, action_type=action_type)

    result = None

    # 3. Decision Tree Router
    if "restart" in action_type:
        pod_name = request.pod_name
        # If pod name is not supplied, locate it in the cluster using labels
        if not pod_name:
            if k8s_configured:
                try:
                    v1 = client.CoreV1Api()
                    pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"app={service}")
                    if pods.items:
                        pod_name = pods.items[0].metadata.name
                        logger.info("Resolved target pod name via labels", pod_name=pod_name, service=service)
                    else:
                        pod_name = f"{service}-pod-fallback"
                except Exception as e:
                    logger.warning("Could not query pods to resolve name, falling back", error=str(e))
                    pod_name = f"{service}-pod-fallback"
            else:
                pod_name = f"{service}-pod-mock"
                
        result = restart_pod(namespace=namespace, pod_name=pod_name)

    elif "rollback" in action_type:
        deployment_name = request.deployment_name or service
        result = rollback_deployment(namespace=namespace, deployment_name=deployment_name)

    elif "scale" in action_type:
        deployment_name = request.deployment_name or service
        replicas = request.replicas if request.replicas is not None else 3
        result = scale_deployment(namespace=namespace, deployment_name=deployment_name, replicas=replicas)

    elif "patch_configmap" in action_type:
        cm_name = request.deployment_name or f"{service}-config"
        patch_data = request.patch or {"data": {"LOG_LEVEL": "INFO"}}
        result = patch_configmap(namespace=namespace, name=cm_name, patch=patch_data)

    elif "open_pr" in action_type or "open_github_pr" in action_type:
        repo = request.repo or "neuroops-project/neuroops"
        branch = f"remediation-{request.incident_id}"
        files = {"cluster/apps/manifests.yaml": f"# Auto-remediation patch\n# Incident: {request.incident_id}\n"}
        result = open_pr(
            repo=repo,
            title=f"remediation: config patch for {service} incident",
            body=request.reasoning,
            branch=branch,
            files=files
        )

    else:
        # Action is 'none' or unknown - escalate to human operator
        logger.info("Remediation escalated (none/unknown action proposed)", incident_id=request.incident_id)
        result = ActionResult(
            success=True,
            action_taken=f"Escalated: No automated remediation executed for hypothesis '{request.hypothesis}'. Reason: action was '{request.recommended_action}'.",
            duration_seconds=0.0
        )

    # 4. Post-Action Verification
    if result.success and request.alert:
        logger.info("Action executed successfully, verifying alert clearance...", incident_id=request.incident_id)
        resolved = verify_resolution(request.alert)
        if not resolved:
            result.success = False
            result.action_taken += " (Warning: incident verification failed/timed out)"

    # Record action history
    actions_history.append(result)
    logger.info("Remediation execution completed", success=result.success, action_taken=result.action_taken)
    return result

@app.get("/actions", response_model=List[ActionResult])
async def get_actions():
    """Returns the history of all remediation actions executed."""
    return actions_history
