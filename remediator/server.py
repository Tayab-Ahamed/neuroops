import json
import os
import socket
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any

import anyio
from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel

# Import actions, verifier, and human loop
from remediator.actions import ActionResult, k8s_configured, logger
from remediator.actions.open_github_pr import open_pr
from remediator.actions.patch_configmap import patch_configmap
from remediator.actions.restart_pod import restart_pod
from remediator.actions.rollback_deploy import rollback_deployment
from remediator.actions.scale_replicas import scale_deployment
from remediator.human_loop import prompt_human
from remediator.store import RemediationStore
from remediator.verifier import verify_resolution

# Prometheus metrics instrumentation
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Histogram,
        generate_latest,
    )

    _prom_registry = CollectorRegistry()
    REMEDIATION_REQUESTS = Counter(
        "neuroops_remediation_requests_total",
        "Total number of /remediate requests received",
        registry=_prom_registry,
    )
    REMEDIATION_SUCCESS = Counter(
        "neuroops_remediation_success_total",
        "Total number of successful remediation actions",
        ["action_type"],
        registry=_prom_registry,
    )
    REMEDIATION_FAILURE = Counter(
        "neuroops_remediation_failure_total",
        "Total number of failed or rejected remediation actions",
        ["reason"],
        registry=_prom_registry,
    )
    REMEDIATION_LATENCY = Histogram(
        "neuroops_remediation_latency_seconds",
        "Latency of remediation action execution",
        buckets=[0.5, 1, 5, 10, 30, 60, 120],
        registry=_prom_registry,
    )
    FLAPPING_LOCKOUTS = Counter(
        "neuroops_flapping_lockouts_total",
        "Number of times anti-flapping lockout was triggered",
        registry=_prom_registry,
    )
    _prom_enabled = True
except ImportError:
    _prom_enabled = False
    _prom_registry = None

# Global history registry of actions taken
actions_history: list[ActionResult] = []
# Global registry of remediation execution timestamps per service for anti-flapping
flapping_history: dict[str, list[float]] = {}
remediation_store = RemediationStore()


class AlertModel(BaseModel):
    id: str
    service: str
    severity: str
    timestamp: float
    metric_snapshot: dict[str, float]
    anomaly_score: float


class RemediationRequest(BaseModel):
    incident_id: str
    hypothesis: str
    confidence: float
    recommended_action: str
    requires_human_approval: bool
    reasoning: str

    # Optional extensions for precise orchestrator control
    alert: AlertModel | dict[str, Any] | None = None
    namespace: str | None = "neuroops-demo"
    pod_name: str | None = None
    deployment_name: str | None = None
    replicas: int | None = None
    patch: dict[str, Any] | None = None
    repo: str | None = None
    auto_approve: bool = False


class HealthResponse(BaseModel):
    status: str
    actions_count: int
    k8s_configured: bool


class SlackInteractionResponse(BaseModel):
    status: str
    message: str


def internal_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": "internal_server_error", "message": detail},
    )


def normalize_action(action: str) -> str:
    return action.strip().lower()


def is_known_action(action: str) -> bool:
    action_type = normalize_action(action)
    return (
        action_type == "none"
        or "restart" in action_type
        or "rollback" in action_type
        or "scale" in action_type
        or "patch_configmap" in action_type
        or "open_pr" in action_type
        or "open_github_pr" in action_type
    )


def _tcp_connect_check(url: str, service_name: str) -> None:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        logger.warning("Startup dependency URL is invalid", service=service_name, url=url)
        return
    try:
        with socket.create_connection((host, port), timeout=3.0):
            logger.info("Startup dependency TCP check succeeded", service=service_name, url=url)
    except OSError as exc:
        logger.warning(
            "Startup dependency TCP check failed",
            service=service_name,
            url=url,
            timeout_seconds=3.0,
            error=str(exc),
        )


async def validate_startup_config() -> None:
    detector_url = os.getenv("DETECTOR_URL")
    agent_url = os.getenv("AGENT_URL")

    if not detector_url:
        detector_url = "http://localhost:8001"
        os.environ["DETECTOR_URL"] = detector_url
        logger.warning("DETECTOR_URL missing at startup; using local default", value=detector_url)
    if not agent_url:
        agent_url = "http://localhost:8002"
        os.environ["AGENT_URL"] = agent_url
        logger.warning("AGENT_URL missing at startup; using local default", value=agent_url)
    if os.getenv("HUMAN_APPROVAL_REQUIRED") is None:
        os.environ["HUMAN_APPROVAL_REQUIRED"] = "true"
        logger.warning(
            "HUMAN_APPROVAL_REQUIRED missing; defaulting to safe mode",
            HUMAN_APPROVAL_REQUIRED=True,
        )

    await anyio.to_thread.run_sync(_tcp_connect_check, detector_url, "detector")
    await anyio.to_thread.run_sync(_tcp_connect_check, agent_url, "agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await validate_startup_config()
    yield


app = FastAPI(
    title="NeuroOps Remediation Engine API",
    version="1.0.0",
    lifespan=lifespan,
)


def extract_service_name(hypothesis: str, reasoning: str) -> str:
    """Helper to parse affected service name from hypothesis/reasoning text."""
    combined = (hypothesis + " " + reasoning).lower()
    if "database-stub" in combined:
        return "database-stub"
    elif "frontend" in combined:
        return "frontend"
    elif "backend" in combined:
        return "backend"
    return "backend"  # Default fallback


from remediator.chatops import send_slack_alert


@app.post(
    "/remediate",
    response_model=ActionResult,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
async def remediate(request: RemediationRequest):
    if not is_known_action(request.recommended_action):
        logger.warning(
            "Rejected remediation request with unknown action",
            incident_id=request.incident_id,
            action=request.recommended_action,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown remediation action",
        )
    try:
        return await _remediate_impl(request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Unexpected error while processing remediation request",
            incident_id=request.incident_id,
            action=request.recommended_action,
            error=str(exc),
            exc_info=True,
        )
        raise internal_error("Failed to process remediation request")


async def _remediate_impl(request: RemediationRequest) -> ActionResult:
    """
    Executes the recommended remediation action based on the RCA hypothesis.
    Invokes human-in-the-loop CLI prompts for actions requiring approval.
    """
    logger.info(
        "Received remediation request",
        incident_id=request.incident_id,
        action=request.recommended_action,
    )

    # Trigger ChatOps Alert (Slack notification / Fallback CLI logging)
    send_slack_alert(
        incident_id=request.incident_id,
        hypothesis=request.hypothesis,
        confidence=request.confidence,
        action=request.recommended_action,
        requires_human_approval=request.requires_human_approval,
    )

    # 1. P2 Check / Human approval loop gate
    if request.requires_human_approval and not request.auto_approve:
        logger.info(
            "Action requires human operator approval, invoking CLI loop",
            incident_id=request.incident_id,
        )
        # Note: prompt_human runs synchronously to wait for operator input (or timeout)
        approved = prompt_human(request, request.recommended_action)
        if not approved:
            result = ActionResult(
                success=False,
                action_taken=f"Rejected: Action '{request.recommended_action}' rejected by human operator or timed out.",
                duration_seconds=0.0,
            )
            actions_history.append(result)
            remediation_store.record_action(
                incident_id=request.incident_id,
                service=extract_service_name(request.hypothesis, request.reasoning),
                action_type=request.recommended_action.lower(),
                success=result.success,
                action_taken=result.action_taken,
                duration_seconds=result.duration_seconds,
                metadata={"requires_human_approval": True, "auto_approve": False, "rejected": True},
            )
            return result

    # 2. Extract service and configurations
    service = extract_service_name(request.hypothesis, request.reasoning)
    namespace = request.namespace or "neuroops-demo"
    action_type = request.recommended_action.lower()

    logger.info(
        "Parsed remediation target details",
        service=service,
        namespace=namespace,
        action_type=action_type,
    )

    # --- Anti-Flapping Filter Gate ---
    import time

    now = time.time()
    if service not in flapping_history:
        flapping_history[service] = remediation_store.recent_success_timestamps(
            service, within_seconds=600.0
        )

    # Purge historical entries older than 10 minutes (600 seconds)
    flapping_history[service] = [t for t in flapping_history[service] if now - t < 600.0]

    if len(flapping_history[service]) >= 2:
        logger.warn(
            "Anti-Flapping Lockout active on service!",
            service=service,
            action_count=len(flapping_history[service]),
        )
        if _prom_enabled:
            FLAPPING_LOCKOUTS.inc()
        result = ActionResult(
            success=False,
            action_taken=f"Rejected: Flapping Lockout Active on service '{service}'. Maximum auto-remediation rate exceeded (2 actions / 10m). Autonomous recovery suspended; escalated to human SRE.",
            duration_seconds=0.0,
        )
        actions_history.append(result)
        remediation_store.record_action(
            incident_id=request.incident_id,
            service=service,
            action_type=action_type,
            success=result.success,
            action_taken=result.action_taken,
            duration_seconds=result.duration_seconds,
            metadata={
                "requires_human_approval": request.requires_human_approval,
                "blocked_by": "flapping_lockout",
            },
        )

        # Still generate a post-mortem report for the blocked action!
        from remediator.postmortem import generate_postmortem

        generate_postmortem(request, result)

        return result

    # Dry-Run mode validation
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    if dry_run:
        logger.info(
            "Dry-Run mode active. Skipping live cluster operations.",
            incident_id=request.incident_id,
        )

        # Simulate Canary Gate
        logger.info("[Canary Gate] Initiating canary scaling verification...", service=service)
        time.sleep(0.5)
        logger.info(
            "[Canary Gate] Canary verified stable. Promoting full remediation.", service=service
        )

        result = ActionResult(
            success=True,
            action_taken=f"[Dry-Run] Verified canary and successfully executed remediation '{request.recommended_action}' on service '{service}' in namespace '{namespace}'",
            duration_seconds=0.6,
        )

        # Log execution in flapping history
        flapping_history[service].append(time.time())

        # Generate Post-Mortem Report
        from remediator.postmortem import generate_postmortem

        generate_postmortem(request, result)

        actions_history.append(result)
        remediation_store.record_action(
            incident_id=request.incident_id,
            service=service,
            action_type=action_type,
            success=result.success,
            action_taken=result.action_taken,
            duration_seconds=result.duration_seconds,
            metadata={"dry_run": True, "requires_human_approval": request.requires_human_approval},
        )
        return result

    result = None

    # 3. Decision Tree Router
    if "restart" in action_type:
        pod_name = request.pod_name
        # If pod name is not supplied, locate it in the cluster using labels
        if not pod_name:
            if k8s_configured:
                try:
                    v1 = client.CoreV1Api()
                    pods = v1.list_namespaced_pod(
                        namespace=namespace, label_selector=f"app={service}"
                    )
                    if pods.items:
                        pod_name = pods.items[0].metadata.name
                        logger.info(
                            "Resolved target pod name via labels",
                            pod_name=pod_name,
                            service=service,
                        )
                    else:
                        pod_name = f"{service}-pod-fallback"
                except ApiException as e:
                    logger.warning(
                        "Could not query pods to resolve name, falling back",
                        status=e.status,
                        reason=e.reason,
                    )
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
        result = scale_deployment(
            namespace=namespace, deployment_name=deployment_name, replicas=replicas
        )

    elif "patch_configmap" in action_type:
        cm_name = request.deployment_name or f"{service}-config"
        patch_data = request.patch or {"data": {"LOG_LEVEL": "INFO"}}
        result = patch_configmap(namespace=namespace, name=cm_name, patch=patch_data)

    elif "open_pr" in action_type or "open_github_pr" in action_type:
        repo = request.repo or "neuroops-project/neuroops"
        branch = f"remediation-{request.incident_id}"
        files = {
            "cluster/apps/manifests.yaml": f"# Auto-remediation patch\n# Incident: {request.incident_id}\n"
        }
        result = open_pr(
            repo=repo,
            title=f"remediation: config patch for {service} incident",
            body=request.reasoning,
            branch=branch,
            files=files,
        )

    else:
        # Action is 'none' or unknown - escalate to human operator
        logger.info(
            "Remediation escalated (none/unknown action proposed)", incident_id=request.incident_id
        )
        result = ActionResult(
            success=True,
            action_taken=f"Escalated: No automated remediation executed for hypothesis '{request.hypothesis}'. Reason: action was '{request.recommended_action}'.",
            duration_seconds=0.0,
        )

    # 4. Post-Action Verification
    if result.success and request.alert:
        logger.info(
            "Action executed successfully, verifying alert clearance...",
            incident_id=request.incident_id,
        )
        resolved = verify_resolution(request.alert)
        if not resolved:
            result.success = False
            result.action_taken += " (Warning: incident verification failed/timed out)"

    # Record execution timestamp for flapping registry on success
    if result.success:
        flapping_history[service].append(time.time())
        if _prom_enabled:
            REMEDIATION_SUCCESS.labels(action_type=action_type).inc()
            REMEDIATION_LATENCY.observe(result.duration_seconds)
    elif not result.success:
        if _prom_enabled:
            REMEDIATION_FAILURE.labels(reason="action_failed").inc()

    # Generate Post-Mortem RCA Report
    from remediator.postmortem import generate_postmortem

    generate_postmortem(request, result)

    # Record action history
    actions_history.append(result)
    remediation_store.record_action(
        incident_id=request.incident_id,
        service=service,
        action_type=action_type,
        success=result.success,
        action_taken=result.action_taken,
        duration_seconds=result.duration_seconds,
        metadata={
            "requires_human_approval": request.requires_human_approval,
            "auto_approve": request.auto_approve,
            "namespace": namespace,
        },
    )
    logger.info(
        "Remediation execution completed", success=result.success, action_taken=result.action_taken
    )
    return result


@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health():
    try:
        return {
            "status": "ok",
            "actions_count": len(remediation_store.list_actions(limit=1000)),
            "k8s_configured": k8s_configured,
        }
    except Exception as exc:
        logger.error("Failed to return remediator health", error=str(exc), exc_info=True)
        raise internal_error("Failed to return remediator health")


@app.get("/metrics", status_code=status.HTTP_200_OK)
async def prometheus_metrics():
    """Exposes Prometheus-format metrics for scraping by Grafana / kube-prometheus."""
    try:
        if not _prom_enabled:
            return Response(content="# prometheus_client not installed", media_type="text/plain")
        return Response(
            content=generate_latest(_prom_registry),
            media_type=CONTENT_TYPE_LATEST,
        )
    except Exception as exc:
        logger.error("Failed to generate remediator metrics", error=str(exc), exc_info=True)
        raise internal_error("Failed to generate remediator metrics")


@app.get(
    "/actions",
    response_model=list[ActionResult],
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
async def get_actions(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Returns the history of all remediation actions executed."""
    try:
        if actions_history:
            return actions_history[offset : offset + limit]
        persisted = remediation_store.list_actions(limit=limit, offset=offset)
        return [
            ActionResult(
                success=item["success"],
                action_taken=item["action_taken"],
                duration_seconds=item["duration_seconds"],
                metadata=item["metadata"],
            )
            for item in persisted
        ]
    except Exception as exc:
        logger.error(
            "Failed to return remediation actions",
            limit=limit,
            offset=offset,
            error=str(exc),
            exc_info=True,
        )
        raise internal_error("Failed to return remediation actions")


@app.post(
    "/slack/interactions",
    response_model=SlackInteractionResponse,
    status_code=status.HTTP_200_OK,
)
async def slack_interactions(request: Request):
    """Receives interactive button clicks from Slack approval notifications."""
    try:
        body = await request.body()
        body_str = body.decode("utf-8")

        parsed = urllib.parse.parse_qs(body_str)
        payload_list = parsed.get("payload")
        if not payload_list:
            return {"status": "error", "message": "No payload found"}

        payload = payload_list[0]
        data = json.loads(payload)
        actions = data.get("actions", [])
        if not actions:
            return {"status": "error", "message": "No actions found"}

        action_val = actions[0].get("value")  # "approved" or "rejected"
        block_id = actions[0].get("block_id", "")  # "approval_{incident_id}"
        incident_id = (
            block_id.replace("approval_", "") if block_id.startswith("approval_") else "unknown"
        )

        logger.info(
            "Received Slack interaction callback", incident_id=incident_id, action_value=action_val
        )

        return {
            "status": "ok",
            "message": f"Remediation {action_val} parsed for incident {incident_id}",
        }
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse Slack interaction payload", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid interaction payload")
    except Exception as exc:
        logger.error(
            "Unexpected Slack interaction handling failure",
            error=str(exc),
            exc_info=True,
        )
        raise internal_error("Failed to process Slack interaction")
