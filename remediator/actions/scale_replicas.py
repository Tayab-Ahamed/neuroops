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


def scale_deployment(namespace: str, deployment_name: str, replicas: int) -> ActionResult:
    """
    Scales a deployment to the requested replica count
    and waits for all replicas to be Ready.

    [!] HPA conflict warning (production guidance)
    -----------------------------------------------
    This function patches ``spec.replicas`` on the Deployment object directly.
    When a HorizontalPodAutoscaler is managing the same Deployment (e.g. the
    HPAs defined in cluster/apps/hpa.yaml), the HPA controller will overwrite
    this value on its next reconciliation cycle (typically within 15-30 s),
    causing a race condition known as "replica drift".

    In a production environment the preferred approach is:
      1. Retrieve the HPA for the Deployment
         (label selector: ``managed-by=neuroops``).
      2. Patch ``spec.minReplicas`` on the HPA to the desired lower-bound.
      3. Optionally patch ``spec.maxReplicas`` if a hard ceiling is also needed.

    Patching the HPA instead of the Deployment hands back control to the
    autoscaler so that scale-down still happens automatically once the incident
    is resolved, without the remediator having to issue a second corrective
    action.

    The current direct-patch implementation is intentionally kept for
    environments where no HPA is present (e.g. local Minikube with low
    resource limits) and for unit-testability without the autoscaling API.
    """
    logger.info(
        "Starting scale_deployment action",
        namespace=namespace,
        deployment_name=deployment_name,
        replicas=replicas,
    )
    start_time = time.time()

    if not k8s_configured:
        logger.info(
            "remediator mock: scale_deployment execution",
            namespace=namespace,
            deployment_name=deployment_name,
            replicas=replicas,
        )
        time.sleep(0.5)
        duration = time.time() - start_time
        return ActionResult(
            success=True,
            action_taken=f"Mock: Scaled deployment '{deployment_name}' to {replicas} replicas (Mock Mode).",
            duration_seconds=duration,
        )

    try:
        apps_v1 = client.AppsV1Api()

        # 1. Check current replicas to check for early exit/idempotency
        try:
            dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        except (ApiException, Exception) as exc:
            if is_not_found(exc):
                logger.warning(
                    "Scale skipped because target deployment was not found",
                    namespace=namespace,
                    deployment=deployment_name,
                    status=exc.status,
                )
                return skipped_not_found(start_time)
            raise

        current_desired = dep.spec.replicas

        if current_desired == replicas:
            logger.info(
                "Deployment is already scaled to target replicas",
                deployment=deployment_name,
                replicas=replicas,
            )
            return ActionResult(
                success=True,
                action_taken="no-op — already at target replicas",
                duration_seconds=time.time() - start_time,
            )
        else:
            # 2. Patch the replica count directly on the Deployment.
            #
            # [!] Production note: if a HorizontalPodAutoscaler (HPA) is active
            # for this Deployment, the HPA controller will overwrite spec.replicas
            # within one reconciliation cycle (~15-30 s), undoing this patch.
            # Prefer patching HPA spec.minReplicas via the autoscaling/v2 API
            # when an HPA with label managed-by=neuroops exists for this
            # Deployment, so the autoscaler remains in control of replica counts.
            body = {"spec": {"replicas": replicas}}
            logger.info(
                "Patching deployment replica count", deployment=deployment_name, replicas=replicas
            )
            apps_v1.patch_namespaced_deployment(
                name=deployment_name, namespace=namespace, body=body
            )

        # 3. Wait for the ready replicas to match the target replicas
        timeout = get_action_timeout_seconds()
        scale_complete = False

        while time.time() - start_time < timeout:
            time.sleep(2)
            try:
                updated_dep = apps_v1.read_namespaced_deployment(
                    name=deployment_name, namespace=namespace
                )
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
            except (ApiException, Exception) as exc:
                logger.warning(
                    "Error checking deployment replica scaling status",
                    namespace=namespace,
                    deployment=deployment_name,
                    status=exc.status,
                    reason=exc.reason,
                )

        duration = time.time() - start_time
        if scale_complete:
            logger.info(
                "Scaling completed successfully",
                deployment=deployment_name,
                replicas=replicas,
                duration=duration,
            )
            return ActionResult(
                success=True,
                action_taken=f"Successfully scaled deployment '{deployment_name}' to {replicas} replicas and verified Ready state.",
                duration_seconds=duration,
            )
        else:
            logger.error(
                "Scaling verification timed out",
                deployment=deployment_name,
                replicas=replicas,
                duration=duration,
            )
            return timeout_result(start_time)

    except (ApiException, Exception) as exc:
        duration = time.time() - start_time
        logger.error(
            "Failed to scale deployment",
            namespace=namespace,
            deployment=deployment_name,
            status=exc.status,
            reason=exc.reason,
        )
        return ActionResult(
            success=False,
            action_taken=(
                f"Failed to scale deployment '{deployment_name}' in namespace "
                f"'{namespace}': {exc.reason}"
            ),
            duration_seconds=duration,
        )
