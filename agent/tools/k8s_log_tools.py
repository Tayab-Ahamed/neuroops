import time
from langchain_core.tools import tool
import structlog
from kubernetes import client, config

logger = structlog.get_logger()

# Check if Kubernetes config is available
try:
    config.load_kube_config()
    k8s_configured = True
except Exception:
    try:
        config.load_incluster_config()
        k8s_configured = True
    except Exception:
        k8s_configured = False

@tool
def get_pod_logs(service_name: str, namespace: str = "neuroops-demo", tail_lines: int = 50) -> str:
    """
    Retrieves the recent container logs for the specified service in the namespace.
    Use this tool to search for stack traces, database connection timeouts, and memory pressure warnings.
    """
    logger.info("Starting get_pod_logs tool", service_name=service_name, namespace=namespace, tail_lines=tail_lines)
    
    if not k8s_configured:
        logger.info("K8s not configured. Generating high-fidelity mock logs.", service_name=service_name)
        return get_mock_logs(service_name)

    try:
        v1 = client.CoreV1Api()
        # Find pod matching the service app label
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"app={service_name}")
        if not pods.items:
            logger.warn("No pods found matching app label", service_name=service_name)
            return f"Error: No active pods found for service '{service_name}' in namespace '{namespace}'."
            
        pod_name = pods.items[0].metadata.name
        logger.info("Found target pod for log retrieval", pod_name=pod_name)
        
        # Pull container logs
        logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=tail_lines)
        return f"=== Logs for pod '{pod_name}' ===\n{logs}"
        
    except Exception as e:
        logger.error("Failed to query live Kubernetes pod logs", service_name=service_name, error=str(e))
        return f"Error querying K8s pod logs for '{service_name}': {str(e)}\n\n[Fallback] Generating mock incident logs:\n{get_mock_logs(service_name)}"


def get_mock_logs(service_name: str) -> str:
    """Generates highly realistic container log streams matching golden signal SRE failure modes."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    if service_name == "backend":
        # Database connection pool timeout simulation
        return (
            f"{timestamp} [WARNING] sqlalchemy.pool.impl.QueuePool: connection pool max overflow 10 reached, connection limit 20 exceeded. Transitioning to wait queue.\n"
            f"{timestamp} [ERROR] ERROR: psycopg2.OperationalError: connection to server at 'database-stub' (10.96.12.44), port 5432 failed: Connection timed out.\n"
            f"{timestamp} [CRITICAL] Internal Server Error: Traceback (most recent call last):\n"
            f"  File '/app/main.py', line 144, in query_db\n"
            f"    db.execute('SELECT * FROM data')\n"
            f"sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) timeout expired\n"
            f"{timestamp} [INFO] 10.244.0.12 - - 'GET /query HTTP/1.1' 500 Internal Server Error"
        )
    elif service_name == "frontend":
        # High CPU starvation event loop block simulation
        return (
            f"{timestamp} [INFO] Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)\n"
            f"{timestamp} [WARNING] asyncio: Event loop blocked for 5.44 seconds. CPU utilization high.\n"
            f"{timestamp} [WARNING] [Performance] Response latency on path '/data' exceeded threshold (duration=6240ms)\n"
            f"{timestamp} [INFO] 10.244.0.1 - - 'GET /health HTTP/1.1' 200 OK\n"
            f"{timestamp} [ERROR] [HTTP] 10.244.0.1 - - 'GET /data HTTP/1.1' 504 Gateway Timeout"
        )
    elif service_name == "database-stub":
        # Memory / disk fill out of space simulation
        return (
            f"{timestamp} [INFO] Starting Postgres Stub server...\n"
            f"{timestamp} [CRITICAL] OOM-killer triggered: Kill process 124 (python) total-vm:4.2GB, anon-rss:256MB\n"
            f"{timestamp} [CRITICAL] FATAL: could not write to log file: No space left on device\n"
            f"{timestamp} [CRITICAL] FATAL: write-ahead log write failed: disk full (85% capacity reached)"
        )
    else:
        # Standard healthy logs
        return (
            f"{timestamp} [INFO] 10.244.0.1 - - 'GET /health HTTP/1.1' 200 OK\n"
            f"{timestamp} [INFO] 10.244.0.12 - - 'GET /metrics HTTP/1.1' 200 OK\n"
            f"{timestamp} [INFO] 10.244.0.5 - - 'GET / HTTP/1.1' 200 OK"
        )
