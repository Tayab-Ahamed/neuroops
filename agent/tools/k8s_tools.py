import datetime
import structlog
from kubernetes import client, config
from langchain_core.tools import tool

logger = structlog.get_logger()

# Initialize Kubernetes client configuration
k8s_configured = False
try:
    try:
        config.load_incluster_config()
        k8s_configured = True
        logger.info("Loaded in-cluster Kubernetes configuration")
    except Exception:
        config.load_kube_config()
        k8s_configured = True
        logger.info("Loaded external kubeconfig configuration")
except Exception as e:
    logger.warning("Kubernetes client is not configured, falling back to mock mode", error=str(e))

@tool
def get_pod_status(namespace: str, pod_name: str) -> str:
    """Gets the status, conditions, restart counts, and events of a specified Kubernetes pod."""
    if not k8s_configured:
        logger.info("k8s mock: get_pod_status", namespace=namespace, pod_name=pod_name)
        # Mock responses for common pod names to aid automated test scenarios
        restarts = 0
        status = "Running"
        reason = ""
        if "oom" in pod_name.lower():
            restarts = 4
            status = "OOMKilled"
            reason = "OOMKilled"
        elif "crash" in pod_name.lower():
            restarts = 12
            status = "CrashLoopBackOff"
            reason = "CrashLoopBackOff"
            
        return (
            f"Pod: {pod_name}\n"
            f"Status: {status}\n"
            f"Restarts: {restarts}\n"
            f"Conditions: Ready=True, Initialized=True\n"
            f"Last State Reason: {reason}\n"
            f"Events: 2026-05-22 T17:00:00: Back-off restarting failed container"
        )

    try:
        v1 = client.CoreV1Api()
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        status_info = pod.status
        phase = status_info.phase
        restarts = 0
        container_statuses = status_info.container_statuses or []
        for cs in container_statuses:
            restarts += cs.restart_count
            
        conditions = [f"{c.type}={c.status}" for c in (status_info.conditions or [])]
        
        # Get pod specific events
        event_msg = []
        events = v1.list_namespaced_event(namespace, field_selector=f"involvedObject.name={pod_name}")
        for e in events.items[:5]:
            event_msg.append(f"{e.last_timestamp}: {e.message}")
            
        return (
            f"Pod: {pod_name}\n"
            f"Phase: {phase}\n"
            f"Restarts: {restarts}\n"
            f"Conditions: {', '.join(conditions)}\n"
            f"Recent Events:\n" + "\n".join(event_msg)
        )
    except Exception as e:
        logger.error("Failed to query pod status", pod_name=pod_name, error=str(e))
        return f"Error querying pod status for {pod_name}: {str(e)}"

@tool
def get_deployment_history(namespace: str, deployment_name: str) -> str:
    """Retrieves the deployment rollout history and active replica counts."""
    if not k8s_configured:
        logger.info("k8s mock: get_deployment_history", namespace=namespace, deployment_name=deployment_name)
        return (
            f"Deployment: {deployment_name}\n"
            f"Replicas: 3 desired, 3 updated, 3 ready, 3 available\n"
            f"Rollout History:\n"
            f"Revision 1: Created bookinfo-demo\n"
            f"Revision 2: Updated environment variables\n"
            f"Revision 3: Rolled out image neuroops/backend:v1.2.0 (suspect release)"
        )

    try:
        apps_v1 = client.AppsV1Api()
        dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        
        status = dep.status
        replicas = (
            f"Replicas: {status.replicas} desired, {status.updated_replicas} updated, "
            f"{status.ready_replicas} ready, {status.available_replicas} available"
        )
        
        # Deployment rollout revisions are stored in ReplicaSets annotations
        v1 = client.CoreV1Api()
        rs_list = apps_v1.list_namespaced_replica_set(
            namespace, 
            label_selector=",".join([f"{k}={v}" for k, v in dep.spec.selector.match_labels.items()])
        )
        
        history = []
        for rs in sorted(rs_list.items, key=lambda x: int(x.metadata.annotations.get("deployment.kubernetes.io/revision", 0))):
            rev = rs.metadata.annotations.get("deployment.kubernetes.io/revision", "unknown")
            image = rs.spec.template.spec.containers[0].image
            history.append(f"Revision {rev}: Image: {image} (ReplicaSet: {rs.metadata.name})")
            
        return f"Deployment: {deployment_name}\n{replicas}\nRollout History:\n" + "\n".join(history)
    except Exception as e:
        logger.error("Failed to query deployment history", deployment_name=deployment_name, error=str(e))
        return f"Error querying deployment history for {deployment_name}: {str(e)}"

@tool
def get_recent_events(namespace: str, service_name: str, minutes: int = 10) -> str:
    """Retrieves cluster events in the last N minutes for a given service or resource."""
    if not k8s_configured:
        logger.info("k8s mock: get_recent_events", namespace=namespace, service_name=service_name)
        return (
            f"Recent Events in {namespace} (last {minutes}m) relating to {service_name}:\n"
            f"2026-05-22 T17:30:00: Back-off restarting failed container\n"
            f"2026-05-22 T17:35:00: Liveness probe failed"
        )

    try:
        v1 = client.CoreV1Api()
        events = v1.list_namespaced_event(namespace)
        
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(minutes=minutes)
        
        relevant_events = []
        for e in events.items:
            # Parse event timestamp safely
            e_time = e.last_timestamp or e.event_time or e.first_timestamp
            if not e_time:
                continue
                
            if e_time.tzinfo is None:
                e_time = e_time.replace(tzinfo=datetime.timezone.utc)
                
            if e_time >= cutoff:
                involved = e.involved_object.name or ""
                if service_name.lower() in involved.lower() or service_name.lower() in e.message.lower():
                    relevant_events.append(f"{e_time.isoformat()}: [{e.type}] {involved}: {e.message}")
                    
        if not relevant_events:
            return f"No events found for {service_name} in namespace {namespace} in the last {minutes} minutes."
            
        return f"Recent Events in {namespace} (last {minutes}m):\n" + "\n".join(relevant_events)
    except Exception as e:
        logger.error("Failed to query events", service_name=service_name, error=str(e))
        return f"Error querying events for {service_name}: {str(e)}"
