import time

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from remediator.actions import (
    ActionResult,
    get_action_timeout_seconds,
    is_not_found,
    k8s_configured,
    logger,
    skipped_not_found,
    timeout_result,
)


def restart_pod(namespace: str, pod_name: str) -> ActionResult:
    """
    Deletes the target pod (allowing K8s controller to recreate it)
    and waits for the new pod to be Ready.
    """
    logger.info("Starting restart_pod action", namespace=namespace, pod_name=pod_name)
    start_time = time.time()

    if not k8s_configured:
        logger.info(
            "remediator mock: restart_pod execution", namespace=namespace, pod_name=pod_name
        )
        # Simulate a small execution duration
        time.sleep(0.5)
        duration = time.time() - start_time
        return ActionResult(
            success=True,
            action_taken=f"Mock: Successfully restarted pod '{pod_name}' in namespace '{namespace}' (Mock Mode).",
            duration_seconds=duration,
        )

    try:
        v1 = client.CoreV1Api()

        # 1. Read pod to verify existence and get labels for recreation tracking.
        try:
            pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            labels = pod.metadata.labels or {}
            label_selector = ",".join([f"{k}={v}" for k, v in labels.items()])
            logger.info("Retrieved pod labels for tracking", pod_name=pod_name, labels=labels)
        except (ApiException, Exception) as exc:
            if is_not_found(exc):
                logger.warning(
                    "Pod restart skipped because target pod was not found",
                    namespace=namespace,
                    pod_name=pod_name,
                    status=exc.status,
                )
                return skipped_not_found(start_time)
            duration = time.time() - start_time
            logger.error(
                "Failed to read pod before restart",
                namespace=namespace,
                pod_name=pod_name,
                status=exc.status,
                reason=exc.reason,
            )
            return ActionResult(
                success=False,
                action_taken=(
                    f"Failed to restart pod '{pod_name}' in namespace '{namespace}': "
                    f"{exc.reason}"
                ),
                duration_seconds=duration,
            )

        if not label_selector:
            app_name = pod_name.split("-")[0]
            label_selector = f"app={app_name}"

        terminating = pod.metadata.deletion_timestamp is not None

        # 2. Delete the pod unless Kubernetes is already terminating it.
        if terminating:
            logger.info(
                "Pod already terminating; waiting for replacement readiness",
                namespace=namespace,
                pod_name=pod_name,
            )
        else:
            logger.info("Deleting namespaced pod", namespace=namespace, pod_name=pod_name)
            try:
                v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            except (ApiException, Exception) as exc:
                if is_not_found(exc):
                    logger.warning(
                        "Pod disappeared before delete; waiting for replacement readiness",
                        namespace=namespace,
                        pod_name=pod_name,
                        status=exc.status,
                    )
                else:
                    duration = time.time() - start_time
                    logger.error(
                        "Failed deleting pod",
                        namespace=namespace,
                        pod_name=pod_name,
                        status=exc.status,
                        reason=exc.reason,
                    )
                    return ActionResult(
                        success=False,
                        action_taken=(
                            f"Failed to restart pod '{pod_name}' in namespace "
                            f"'{namespace}': {exc.reason}"
                        ),
                        duration_seconds=duration,
                    )

        # 3. Wait for the pod to be recreated and Ready.
        timeout = get_action_timeout_seconds()
        recreated_and_ready = False

        while time.time() - start_time < timeout:
            time.sleep(2)
            try:
                pods_list = v1.list_namespaced_pod(
                    namespace=namespace, label_selector=label_selector
                )
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
            except (ApiException, Exception) as exc:
                logger.warning(
                    "Error listing pods during recreation check",
                    namespace=namespace,
                    pod_name=pod_name,
                    status=exc.status,
                    reason=exc.reason,
                )

        duration = time.time() - start_time
        if recreated_and_ready:
            logger.info("Pod restart completed successfully", pod_name=pod_name, duration=duration)
            return ActionResult(
                success=True,
                action_taken=f"Successfully restarted pod '{pod_name}' in namespace '{namespace}' and verified Ready state.",
                duration_seconds=duration,
            )
        else:
            logger.error("Pod restart verification timed out", pod_name=pod_name, duration=duration)
            return timeout_result(start_time)

    except (ApiException, Exception) as exc:
        duration = time.time() - start_time
        logger.error(
            "Failed to execute restart_pod",
            namespace=namespace,
            pod_name=pod_name,
            status=exc.status,
            reason=exc.reason,
        )
        return ActionResult(
            success=False,
            action_taken=(
                f"Failed to restart pod '{pod_name}' in namespace '{namespace}': {exc.reason}"
            ),
            duration_seconds=duration,
        )
