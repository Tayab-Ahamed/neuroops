import os
import time
import structlog
from prometheus_api_client import PrometheusConnect
from langchain_core.tools import tool
from typing import List, Tuple

logger = structlog.get_logger()

# Initialize Prometheus client
prom_url = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
prom_configured = False
try:
    prom = PrometheusConnect(url=prom_url, disable_ssl=True)
    if prom.check_prometheus_connection():
        prom_configured = True
        logger.info("Successfully connected to Prometheus server", url=prom_url)
    else:
        logger.warning("Prometheus connection check failed, using mock metrics")
except Exception as e:
    logger.warning("Failed to configure Prometheus connection, using mock metrics", error=str(e))

@tool
def query_metric(promql: str, minutes: int = 10) -> str:
    """Queries Prometheus metrics using a raw PromQL string for the last N minutes and returns the values."""
    if not prom_configured:
        logger.info("prometheus mock: query_metric", promql=promql, minutes=minutes)
        # Mock time-series output
        now = time.time()
        points = []
        for i in range(5):
            t = now - (5 - i) * 60
            points.append((t, 5.0 + i * 2.5 if "cpu" in promql.lower() else 0.05))
        return f"PromQL Query: {promql}\nTime Series Results:\n" + "\n".join([f"{ts:.1f}: {val}" for ts, val in points])

    try:
        from datetime import datetime, timedelta
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=minutes)
        
        results = prom.custom_query_range(
            query=promql,
            start_time=start_time,
            end_time=end_time,
            step="1m"
        )
        
        output = []
        for res in results:
            metric_info = res.get("metric", {})
            values = res.get("values", [])
            output.append(f"Metric: {metric_info}")
            for v in values:
                output.append(f"  {v[0]}: {v[1]}")
                
        if not output:
            return f"No metrics returned for query: {promql}"
            
        return "\n".join(output)
    except Exception as e:
        logger.error("Failed to run PromQL query", query=promql, error=str(e))
        return f"Error executing PromQL query {promql}: {str(e)}"

@tool
def compare_services(metric: str, time_window: str = "5m") -> str:
    """Compares the specified Golden Signal metric (latency, error_rate, traffic, saturation) across all microservices (frontend, backend, database)."""
    if not prom_configured:
        logger.info("prometheus mock: compare_services", metric=metric, time_window=time_window)
        # Return mock Golden Signal comparisons
        if "error" in metric.lower():
            return (
                f"Golden Signal Service Comparison - Error Rate ({time_window}):\n"
                f"- frontend: 0.0 (normal)\n"
                f"- backend: 0.22 (ANOMALOUS - high error rate on API calls)\n"
                f"- database: 0.0 (normal)"
            )
        elif "latency" in metric.lower():
            return (
                f"Golden Signal Service Comparison - P95 Latency ({time_window}):\n"
                f"- frontend: 2.15s (ANOMALOUS - waiting on backend)\n"
                f"- backend: 2.05s (ANOMALOUS - waiting on DB or slow processing)\n"
                f"- database: 0.02s (normal)"
            )
        elif "cpu" in metric.lower() or "saturation" in metric.lower():
            return (
                f"Golden Signal Service Comparison - Saturation ({time_window}):\n"
                f"- frontend: CPU: 12%, Memory: 45%\n"
                f"- backend: CPU: 95% (ANOMALOUS - high load), Memory: 80%\n"
                f"- database: CPU: 8%, Memory: 30Node%"
            )
        else:
            return (
                f"Golden Signal Service Comparison - Traffic ({time_window}):\n"
                f"- frontend: 120 req/sec\n"
                f"- backend: 118 req/sec\n"
                f"- database: 240 req/sec"
            )

    try:
        # Build queries based on standard Golden Signals
        queries = {}
        if "latency" in metric.lower():
            queries = {
                "frontend": f"histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{job=\"frontend-service\"}}[{time_window}])) by (le))",
                "backend": f"histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{job=\"backend-service\"}}[{time_window}])) by (le))",
                "database": f"histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{job=\"database-service\"}}[{time_window}])) by (le))"
            }
        elif "error" in metric.lower():
            queries = {
                "frontend": f"sum(rate(http_requests_total{{job=\"frontend-service\",status=~\"5..\"}}[{time_window}])) / sum(rate(http_requests_total{{job=\"frontend-service\"}}[{time_window}]))",
                "backend": f"sum(rate(http_requests_total{{job=\"backend-service\",status=~\"5..\"}}[{time_window}])) / sum(rate(http_requests_total{{job=\"backend-service\"}}[{time_window}]))",
                "database": f"sum(rate(http_requests_total{{job=\"database-service\",status=~\"5..\"}}[{time_window}])) / sum(rate(http_requests_total{{job=\"database-service\"}}[{time_window}]))"
            }
        elif "cpu" in metric.lower() or "saturation" in metric.lower():
            queries = {
                "frontend": f"sum(rate(container_cpu_usage_seconds_total{{container=\"frontend-service\"}}[1m]))",
                "backend": f"sum(rate(container_cpu_usage_seconds_total{{container=\"backend-service\"}}[1m]))",
                "database": f"sum(rate(container_cpu_usage_seconds_total{{container=\"database-service\"}}[1m]))"
            }
        else: # Default: Traffic
            queries = {
                "frontend": f"sum(rate(http_requests_total{{job=\"frontend-service\"}}[{time_window}]))",
                "backend": f"sum(rate(http_requests_total{{job=\"backend-service\"}}[{time_window}]))",
                "database": f"sum(rate(http_requests_total{{job=\"database-service\"}}[{time_window}]))"
            }

        comparison = [f"Golden Signal Service Comparison - {metric.capitalize()} ({time_window}):"]
        for svc, q in queries.items():
            res = prom.custom_query(q)
            val = "0.0"
            if res and len(res) > 0:
                val_data = res[0].get("value")
                if val_data and len(val_data) == 2:
                    val = val_data[1]
            comparison.append(f"- {svc}: {val}")
            
        return "\n".join(comparison)
    except Exception as e:
        logger.error("Failed to compare service signals", metric=metric, error=str(e))
        return f"Error executing compare_services for {metric}: {str(e)}"
