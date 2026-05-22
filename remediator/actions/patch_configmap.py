import time
from kubernetes import client
from remediator.actions import ActionResult, k8s_configured, logger

def patch_configmap(namespace: str, name: str, patch: dict) -> ActionResult:
    """
    Applies a strategic merge patch to the target ConfigMap.
    """
    logger.info("Starting patch_configmap action", namespace=namespace, name=name, patch=patch)
    start_time = time.time()

    if not k8s_configured:
        logger.info("remediator mock: patch_configmap execution", namespace=namespace, name=name, patch=patch)
        time.sleep(0.5)
        duration = time.time() - start_time
        return ActionResult(
            success=True,
            action_taken=f"Mock: Patched ConfigMap '{name}' in namespace '{namespace}' (Mock Mode).",
            duration_seconds=duration
        )

    try:
        v1 = client.CoreV1Api()
        
        # Apply the strategic merge patch
        logger.info("Applying merge patch to ConfigMap", name=name, namespace=namespace)
        v1.patch_namespaced_config_map(name=name, namespace=namespace, body=patch)
        
        duration = time.time() - start_time
        logger.info("ConfigMap patched successfully", name=name, duration=duration)
        return ActionResult(
            success=True,
            action_taken=f"Successfully patched ConfigMap '{name}' in namespace '{namespace}'.",
            duration_seconds=duration
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("Failed to patch ConfigMap", name=name, error=str(e))
        return ActionResult(
            success=False,
            action_taken=f"Failed to patch ConfigMap '{name}' in namespace '{namespace}': {str(e)}",
            duration_seconds=duration
        )
