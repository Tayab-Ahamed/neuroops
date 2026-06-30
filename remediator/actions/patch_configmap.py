import time

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from remediator.actions import ActionResult, is_not_found, k8s_configured, logger, skipped_not_found


def patch_configmap(namespace: str, name: str, patch: dict) -> ActionResult:
    """
    Applies a strategic merge patch to the target ConfigMap.
    """
    logger.info("Starting patch_configmap action", namespace=namespace, name=name, patch=patch)
    start_time = time.time()

    if not k8s_configured:
        logger.info(
            "remediator mock: patch_configmap execution",
            namespace=namespace,
            name=name,
            patch=patch,
        )
        time.sleep(0.5)
        duration = time.time() - start_time
        return ActionResult(
            success=True,
            action_taken=f"Mock: Patched ConfigMap '{name}' in namespace '{namespace}' (Mock Mode).",
            duration_seconds=duration,
        )

    try:
        v1 = client.CoreV1Api()

        try:
            v1.read_namespaced_config_map(name=name, namespace=namespace)
        except (ApiException, Exception) as exc:
            if is_not_found(exc):
                logger.warning(
                    "ConfigMap patch skipped because target ConfigMap was not found",
                    namespace=namespace,
                    name=name,
                    status=exc.status,
                )
                return skipped_not_found(start_time)
            raise

        # Apply the strategic merge patch
        logger.info("Applying merge patch to ConfigMap", name=name, namespace=namespace)
        v1.patch_namespaced_config_map(name=name, namespace=namespace, body=patch)

        duration = time.time() - start_time
        logger.info("ConfigMap patched successfully", name=name, duration=duration)
        return ActionResult(
            success=True,
            action_taken=f"Successfully patched ConfigMap '{name}' in namespace '{namespace}'.",
            duration_seconds=duration,
        )

    except (ApiException, Exception) as exc:
        duration = time.time() - start_time
        logger.error(
            "Failed to patch ConfigMap",
            namespace=namespace,
            name=name,
            status=exc.status,
            reason=exc.reason,
        )
        return ActionResult(
            success=False,
            action_taken=(
                f"Failed to patch ConfigMap '{name}' in namespace '{namespace}': {exc.reason}"
            ),
            duration_seconds=duration,
        )
