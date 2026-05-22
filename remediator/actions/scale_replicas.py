import time
from kubernetes import client
from remediator.actions import ActionResult, k8s_configured, logger

def scale_deployment(namespace: str, deployment_name: str, replicas: int) -> ActionResult:
    """
    Scales a deployment to the requested replica count
    and waits up to 60 seconds for all replicas to be Ready.
    """
    logger.info("Starting scale_deployment action", namespace=namespace, deployment_name=deployment_name, replicas=replicas)
    start_time = time.time()

    if not k8s_configured:
        logger.info("remediator mock: scale_deployment execution", namespace=namespace, deployment_name=deployment_name, replicas=replicas)
        time.sleep(0.5)
        duration = time.time() - start_time
        return ActionResult(
            success=True,
            action_taken=f"Mock: Scaled deployment '{deployment_name}' to {replicas} replicas (Mock Mode).",
            duration_seconds=duration
        )

    try:
        apps_v1 = client.AppsV1Api()
        
        # 1. Check current replicas to check for early exit/idempotency
        dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        current_desired = dep.spec.replicas
        
        if current_desired == replicas:
            logger.info("Deployment is already scaled to target replicas. Checking status...", deployment=deployment_name, replicas=replicas)
            # Idempotency check: if already at target, we just verify ready replicas
        else:
            # 2. Patch the replica count
            body = {"spec": {"replicas": replicas}}
            logger.info("Patching deployment replica count", deployment=deployment_name, replicas=replicas)
            apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)

        # 3. Wait up to 60 seconds for the ready replicas to match the target replicas
        timeout = 60
        scale_complete = False
        
        while time.time() - start_time < timeout:
            time.sleep(2)
            try:
                updated_dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
                status = updated_dep.status
                
                # Check status replicas
                ready_replicas = status.ready_replicas or 0
                updated_replicas = status.updated_replicas or 0
                
                # If target is 0, ready and updated replicas will be 0/None
                if replicas == 0:
                    # In K8s, if scale is 0, status.replicas is None/0, status.ready_replicas is None
                    current_replicas = status.replicas or 0
                    if current_replicas == 0:
                        scale_complete = True
                        break
                else:
                    if ready_replicas == replicas and updated_replicas == replicas:
                        scale_complete = True
                        break
            except Exception as e:
                logger.warning("Error checking deployment replica scaling status", error=str(e))

        duration = time.time() - start_time
        if scale_complete:
            logger.info("Scaling completed successfully", deployment=deployment_name, replicas=replicas, duration=duration)
            return ActionResult(
                success=True,
                action_taken=f"Successfully scaled deployment '{deployment_name}' to {replicas} replicas and verified Ready state.",
                duration_seconds=duration
            )
        else:
            logger.error("Scaling verification timed out", deployment=deployment_name, replicas=replicas, duration=duration)
            return ActionResult(
                success=False,
                action_taken=f"Scaled deployment '{deployment_name}' to {replicas} replicas, but verification timed out (60s).",
                duration_seconds=duration
            )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("Failed to scale deployment", deployment=deployment_name, error=str(e))
        return ActionResult(
            success=False,
            action_taken=f"Failed to scale deployment '{deployment_name}' in namespace '{namespace}': {str(e)}",
            duration_seconds=duration
        )
