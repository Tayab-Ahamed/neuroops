import os
import time

import structlog
from prometheus_api_client import PrometheusConnect
from pydantic import BaseModel

logger = structlog.get_logger()


class MetricWindow(BaseModel):
    service_name: str
    timestamp: float
    feature_vector: dict[str, float]


class PrometheusScraper:
    def __init__(self, prometheus_url: str | None = None):
        self.url = prometheus_url or os.getenv("PROMETHEUS_URL", "http://localhost:9090")
        logger.info("Initializing PrometheusScraper", prometheus_url=self.url)
        self.prom = PrometheusConnect(url=self.url, disable_ssl=True)
        # Services we expect to monitor
        self.target_services = ["frontend", "backend", "database-stub"]

    def _normalize_service_name(self, raw_name: str) -> str | None:
        """Normalizes job or container names to frontend, backend, or database-stub."""
        clean_name = raw_name.lower().strip()
        if "frontend" in clean_name:
            return "frontend"
        elif "backend" in clean_name:
            return "backend"
        elif "database-stub" in clean_name or "db-stub" in clean_name or "database" in clean_name:
            return "database-stub"
        return None

    def _run_query(self, query: str) -> list[dict]:
        """Runs custom PromQL query using prometheus-api-client with error handling."""
        try:
            results = self.prom.custom_query(query=query)
            return results or []
        except Exception as e:
            logger.error("Prometheus query failed", query=query, error=str(e))
            return []

    def scrape_metrics(self) -> list[MetricWindow]:
        """Scrapes all Golden Signals from Prometheus and builds MetricWindow objects."""
        logger.info("Starting metrics scrape cycle")
        timestamp = time.time()

        # 1. Define PromQL queries
        queries = {
            "request_rate": "sum(rate(http_requests_total[1m])) by (job)",
            "error_requests": 'sum(rate(http_requests_total{status=~"5.."}[1m])) by (job)',
            "p50_latency": "histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[1m])) by (le, job))",
            "p95_latency": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le, job))",
            "p99_latency": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[1m])) by (le, job))",
            "cpu_usage": 'sum(rate(container_cpu_usage_seconds_total{container!="",namespace="neuroops-demo"}[1m])) by (container)',
            "memory_usage": 'sum(container_memory_working_set_bytes{container!="",namespace="neuroops-demo"}) by (container)',
            "pod_restarts": 'sum(delta(kube_pod_container_status_restarts_total{container!="",namespace="neuroops-demo"}[1m])) by (container)',
        }

        # Structure to accumulate raw data per service
        # service_name -> feature_name -> value
        raw_data: dict[str, dict[str, float]] = {
            svc: {
                "p50_latency": 0.0,
                "p95_latency": 0.0,
                "p99_latency": 0.0,
                "request_rate": 0.0,
                "error_rate": 0.0,
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "pod_restarts": 0.0,
            }
            for svc in self.target_services
        }

        # Keep track of error requests vs total requests to calculate error rate
        error_requests_count: dict[str, float] = dict.fromkeys(self.target_services, 0.0)
        total_requests_count: dict[str, float] = dict.fromkeys(self.target_services, 0.0)

        for feature_name, query in queries.items():
            results = self._run_query(query)
            for res in results:
                metric = res.get("metric", {})
                value_data = res.get("value", [])

                # Extract value
                value = 0.0
                if len(value_data) == 2:
                    try:
                        val_str = value_data[1]
                        if val_str != "NaN":
                            value = float(val_str)
                    except ValueError:
                        pass

                # Identify service name from labels
                raw_service = metric.get("job") or metric.get("container")
                if not raw_service:
                    continue

                service = self._normalize_service_name(raw_service)
                if not service or service not in self.target_services:
                    continue

                if feature_name == "error_requests":
                    error_requests_count[service] = value
                elif feature_name == "request_rate":
                    total_requests_count[service] = value
                    raw_data[service]["request_rate"] = value
                elif feature_name in [
                    "p50_latency",
                    "p95_latency",
                    "p99_latency",
                    "cpu_usage",
                    "memory_usage",
                    "pod_restarts",
                ]:
                    raw_data[service][feature_name] = value

        # Compute error rate and construct output
        windows: list[MetricWindow] = []
        for service in self.target_services:
            errors = error_requests_count[service]
            total = total_requests_count[service]

            # Compute error rate
            error_rate = 0.0
            if total > 0:
                error_rate = errors / total

            raw_data[service]["error_rate"] = error_rate

            # Create MetricWindow
            window = MetricWindow(
                service_name=service, timestamp=timestamp, feature_vector=raw_data[service]
            )
            windows.append(window)
            logger.info("Scraped service metrics", service=service, features=raw_data[service])

        return windows
