import time
from kubernetes import client
from remediator.actions import ActionResult, k8s_configured, logger

def restart_pod(namespace: str, pod_name: str) -> ActionResult:
    """
    Deletes the target pod (allowing K8s controller to recreate it)
    and waits up to 60 seconds for the new pod to be Ready.
    """
    logger.info("Starting restart_pod action", namespace=namespace, pod_name=pod_name)
    start_time = time.time()

    if not k8s_configured:
        logger.info("remediator mock: restart_pod execution", namespace=namespace, pod_name=pod_name)
        # Simulate a small execution duration
        time.sleep(0.5)
        duration = time.time() - start_time
        return ActionResult(
            success=True,
            action_taken=f"Mock: Successfully restarted pod '{pod_name}' in namespace '{namespace}' (Mock Mode).",
            duration_seconds=duration
        )

    try:
        v1 = client.CoreV1Api()
        
        # 1. Read pod to get labels for recreating tracking
        try:
            pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            labels = pod.metadata.labels or {}
            label_selector = ",".join([f"{k}={v}" for k, v in labels.items()])
            logger.info("Retrieved pod labels for tracking", pod_name=pod_name, labels=labels)
        except Exception as e:
            logger.warning("Could not read pod metadata before delete, using default labels", pod_name=pod_name, error=str(e))
            # Fallback label selector based on common name formats
            app_name = pod_name.split("-")[0]
            label_selector = f"app={app_name}"

        # 2. Delete the pod
        logger.info("Deleting namespaced pod", namespace=namespace, pod_name=pod_name)
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)

        # 3. Wait up to 60 seconds for the pod to be recreated and Ready
        timeout = 60
        recreated_and_ready = False
        
        while time.time() - start_time < timeout:
            time.sleep(2)
            try:
                pods_list = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
                if not pods_list.items:
                    continue
                
                all_ready = True
                found_new = False
                for p in pods_list.items:
                    # Check if pod is running and ready
                    phase = p.status.phase
                    if phase != "Running":
                        all_ready = False
                        continue
                    
                    container_statuses = p.status.container_statuses or []
                    if not container_statuses:
                        all_ready = False
                        continue
                    
                    for cs in container_statuses:
                        if not cs.ready:
                            all_ready = False
                            break
                    
                    if p.metadata.name != pod_name:
                        found_new = True

                # If all current pods matching the selector are Running & Ready, and we either found a new pod
                # or the pod is healthy, we succeed!
                if all_ready and (found_new or len(pods_list.items) > 0):
                    recreated_and_ready = True
                    break
            except Exception as e:
                logger.warning("Error listing pods during recreation check", error=str(e))

        duration = time.time() - start_time
        if recreated_and_ready:
            logger.info("Pod restart completed successfully", pod_name=pod_name, duration=duration)
            return ActionResult(
                success=True,
                action_taken=f"Successfully restarted pod '{pod_name}' in namespace '{namespace}' and verified Ready state.",
                duration_seconds=duration
            )
        else:
            logger.error("Pod restart verification timed out", pod_name=pod_name, duration=duration)
            return ActionResult(
                success=False,
                action_taken=f"Restarted pod '{pod_name}' in namespace '{namespace}' but verification timed out (60s).",
                duration_seconds=duration
            )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("Failed to execute restart_pod", pod_name=pod_name, error=str(e))
        return ActionResult(
            success=False,
            action_taken=f"Failed to restart pod '{pod_name}' in namespace '{namespace}': {str(e)}",
            duration_seconds=duration
        )
