import os
import time
import structlog
import httpx
from langchain_core.tools import tool

logger = structlog.get_logger()

jaeger_url = os.getenv("JAEGER_QUERY_URL", "http://localhost:16686")
jaeger_configured = False

try:
    # Check connection to Jaeger UI/API
    response = httpx.get(f"{jaeger_url}/api/dependencies", timeout=2.0)
    if response.status_code == 200:
        jaeger_configured = True
        logger.info("Successfully connected to Jaeger server", url=jaeger_url)
except Exception as e:
    logger.warning("Jaeger server is not configured or offline, running Jaeger tools in mock mode", error=str(e))

@tool
def get_service_dependencies(service_name: str) -> str:
    """Queries Jaeger to retrieve upstream and downstream dependencies and latency bottlenecks for a service."""
    if not jaeger_configured:
        logger.info("jaeger mock: get_service_dependencies", service_name=service_name)
        # Realistic dependencies for the bookinfo / neuroops stack
        if "frontend" in service_name.lower():
            return (
                f"Service Dependency Analysis for {service_name}:\n"
                f"- Upstream: None (Entrypoint)\n"
                f"- Downstream: backend-service (P95 Latency: 2.05s, anomalous)\n"
                f"- Bottleneck: backend-service"
            )
        elif "backend" in service_name.lower():
            return (
                f"Service Dependency Analysis for {service_name}:\n"
                f"- Upstream: frontend-service\n"
                f"- Downstream: database-service (P95 Latency: 0.02s, normal)\n"
                f"- Bottleneck: backend-service self-latency"
            )
        else:
            return (
                f"Service Dependency Analysis for {service_name}:\n"
                f"- Upstream: backend-service\n"
                f"- Downstream: None\n"
                f"- Bottleneck: None"
            )

    try:
        # Query Jaeger dependencies API
        # Jaeger returns dependency links: [{'parent': '...', 'child': '...', 'callCount': ...}]
        response = httpx.get(f"{jaeger_url}/api/dependencies", params={"endMs": int(time.time() * 1000)}, timeout=5.0)
        if response.status_code == 200:
            links = response.json().get("data", [])
            upstream = []
            downstream = []
            for link in links:
                parent = link.get("parent")
                child = link.get("child")
                if parent == service_name:
                    downstream.append(child)
                if child == service_name:
                    upstream.append(parent)
                    
            return (
                f"Service Dependency Analysis for {service_name}:\n"
                f"- Upstream: {', '.join(upstream) if upstream else 'None'}\n"
                f"- Downstream: {', '.join(downstream) if downstream else 'None'}\n"
                f"- Bottleneck: Unable to detect live bottleneck automatically, investigate trace details."
            )
        return f"Error querying Jaeger dependencies: Status code {response.status_code}"
    except Exception as e:
        logger.error("Failed to query Jaeger dependencies", service=service_name, error=str(e))
        return f"Error querying Jaeger: {str(e)}"
  
