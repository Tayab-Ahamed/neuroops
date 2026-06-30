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


def rollback_deployment(namespace: str, deployment_name: str) -> ActionResult:
    """
    Rolls back a deployment to its previous revision (like rollout undo)
    and waits for the rollout to complete.
    """
    logger.info(
        "Starting rollback_deployment action", namespace=namespace, deployment_name=deployment_name
    )
    start_time = time.time()

    if not k8s_configured:
        logger.info(
            "remediator mock: rollback_deployment execution",
            namespace=namespace,
            deployment_name=deployment_name,
        )
        time.sleep(0.5)
        duration = time.time() - start_time
        return ActionResult(
            success=True,
            action_taken=f"Mock: Rolled back deployment '{deployment_name}' from revision 3 to revision 2 (Mock Mode).",
            duration_seconds=duration,
        )

    try:
        apps_v1 = client.AppsV1Api()

        # 1. Read deployment to get current generation and annotations
        try:
            dep = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        except (ApiException, Exception) as exc:
            if is_not_found(exc):
                logger.warning(
                    "Rollback skipped because target deployment was not found",
                    namespace=namespace,
                    deployment=deployment_name,
                    status=exc.status,
                )
                return skipped_not_found(start_time)
            raise

        annotations = dep.metadata.annotations or {}
        current_revision = annotations.get("deployment.kubernetes.io/revision")
        if not current_revision:
            logger.warning(
                "No current revision found in deployment annotations, assuming 1",
                deployment=deployment_name,
            )
            current_revision = "1"

        current_rev_int = int(current_revision)
        current_images = [
            container.image
            for container in (dep.spec.template.spec.containers or [])
            if getattr(container, "image", None)
        ]

        # 2. Get all ReplicaSets for this deployment
        match_labels = dep.spec.selector.match_labels or {}
        label_selector = ",".join([f"{k}={v}" for k, v in match_labels.items()])

        rs_list = apps_v1.list_namespaced_replica_set(namespace, label_selector=label_selector)

        revisions = []
        for rs in rs_list.items:
            rev = (rs.metadata.annotations or {}).get("deployment.kubernetes.io/revision")
            if rev is not None:
                revisions.append((int(rev), rs))

        revisions.sort(key=lambda x: x[0])

        if not revisions or len(revisions) < 2:
            duration = time.time() - start_time
            logger.warn("No previous revision available for rollback", deployment=deployment_name)
            return ActionResult(
                success=False,
                action_taken=f"Failed rollback: Deployment '{deployment_name}' has no previous revision history.",
                duration_seconds=duration,
            )

        # Find the previous revision ReplicaSet (highest revision less than current_rev_int)
        prev_rs = None
        for rev_num, rs in reversed(revisions):
            if rev_num < current_rev_int:
                prev_rs = rs
                break

        if not prev_rs:
            # Fallback to the lowest available revision if no revision is less than current
            prev_rs = revisions[0][1]

        prev_rev_num = (prev_rs.metadata.annotations or {}).get("deployment.kubernetes.io/revision")
        logger.info(
            "Found target revision ReplicaSet for rollback",
            deployment=deployment_name,
            from_revision=current_revision,
            to_revision=prev_rev_num,
            rs_name=prev_rs.metadata.name,
        )

        # 3. Patch deployment spec template with the previous RS template spec
        api_client = client.ApiClient()
        # Serialize the V1PodTemplateSpec spec object safely using client's official serializer
        spec_dict = api_client.sanitize_for_serialization(prev_rs.spec.template.spec)

        body = {"spec": {"template": {"spec": spec_dict}}}

        # We also want to record which revision we rolled back from/to in deployment annotations
        body["metadata"] = {
            "annotations": {
                "neuroops.io/remediation-action": "rollback",
                "neuroops.io/rollback-from": str(current_revision),
                "neuroops.io/rollback-to": str(prev_rev_num),
            }
        }

        logger.info("Patching deployment spec template for rollback", deployment=deployment_name)
        apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)

        # 4. Wait for rollout to complete
        timeout = get_action_timeout_seconds()
        rollout_complete = False

        while time.time() - start_time < timeout:
            time.sleep(2)
            try:
                updated_dep = apps_v1.read_namespaced_deployment(
                    name=deployment_name, namespace=namespace
                )
                status = updated_dep.status
                spec = updated_dep.spec

                # Check status conditions for complete rollout
                observed_generation = status.observed_generation or 0
                generation = updated_dep.metadata.generation or 0

                updated_replicas = status.updated_replicas or 0
                desired_replicas = spec.replicas or 0
                ready_replicas = status.ready_replicas or 0
                available_replicas = status.available_replicas or 0

                if (
                    observed_generation >= generation
                    and updated_replicas == desired_replicas
                    and ready_replicas == desired_replicas
                    and available_replicas == desired_replicas
                ):
                    rollout_complete = True
                    break
            except (ApiException, Exception) as exc:
                logger.warning(
                    "Error checking deployment rollout status",
                    namespace=namespace,
                    deployment=deployment_name,
                    status=exc.status,
                    reason=exc.reason,
                )

        duration = time.time() - start_time
        if rollout_complete:
            logger.info(
                "Rollback rollout completed successfully",
                deployment=deployment_name,
                duration=duration,
            )
            return ActionResult(
                success=True,
                action_taken=(
                    f"Successfully rolled back deployment '{deployment_name}' "
                    f"from revision {current_revision} to revision {prev_rev_num} and verified healthy rollout."
                ),
                duration_seconds=duration,
                metadata={
                    "current_image_tags": current_images,
                    "from_revision": str(current_revision),
                    "to_revision": str(prev_rev_num),
                },
            )
        else:
            logger.error(
                "Rollback rollout verification timed out",
                deployment=deployment_name,
                duration=duration,
            )
            result = timeout_result(start_time)
            result.metadata = {
                "current_image_tags": current_images,
                "from_revision": str(current_revision),
                "to_revision": str(prev_rev_num),
            }
            return result

    except (ApiException, Exception) as exc:
        duration = time.time() - start_time
        logger.error(
            "Failed to execute rollback_deployment",
            namespace=namespace,
            deployment=deployment_name,
            status=exc.status,
            reason=exc.reason,
        )
        return ActionResult(
            success=False,
            action_taken=(
                f"Failed to rollback deployment '{deployment_name}' in namespace "
                f"'{namespace}': {exc.reason}"
            ),
            duration_seconds=duration,
        )
