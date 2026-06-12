import datetime
import sys

import structlog
from models.isolation_forest import IsolationForestModel
from models.sequence_forecaster import SequenceForecastModel
from scraper import MetricWindow, PrometheusScraper

# Configure standard console logging
structlog.configure(
    processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()]
)
logger = structlog.get_logger()


def collect_historical_baseline(
    scraper: PrometheusScraper, minutes: int = 30, step_seconds: int = 15
) -> list[MetricWindow]:
    """Queries historical metrics from Prometheus to instantly build a baseline dataset."""
    logger.info("Starting historical baseline data collection", duration_minutes=minutes)

    end_time = datetime.datetime.now()
    start_time = end_time - datetime.timedelta(minutes=minutes)

    # We will fetch historical range metrics for each of our required PromQL queries
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

    # Step in Prometheus format (e.g. "15s")
    step = f"{step_seconds}s"

    # Structure to build metric windows: timestamp -> service_name -> feature_name -> value
    # Since range queries return snapshots at regular intervals, we align them by timestamps
    timestamped_data: dict[int, dict[str, dict[str, float]]] = {}

    target_services = scraper.target_services

    for feature_name, query in queries.items():
        try:
            logger.info("Executing range query", feature=feature_name)
            results = scraper.prom.custom_query_range(
                query=query, start_time=start_time, end_time=end_time, step=step
            )

            for res in results:
                metric = res.get("metric", {})
                values = res.get("values", [])  # List of [timestamp, value]

                raw_service = metric.get("job") or metric.get("container")
                if not raw_service:
                    continue

                service = scraper._normalize_service_name(raw_service)
                if not service or service not in target_services:
                    continue

                for ts_val in values:
                    if len(ts_val) != 2:
                        continue

                    raw_ts, val_str = ts_val
                    # Align to nearest integer timestamp to handle minor float deviations
                    ts = int(float(raw_ts))

                    value = 0.0
                    try:
                        if val_str != "NaN":
                            value = float(val_str)
                    except ValueError as exc:
                        logger.warning(
                            "Failed to parse Prometheus historical metric value",
                            service=raw_service,
                            metric=feature_name,
                            timestamp=ts,
                            raw_value=val_str,
                            error=str(exc),
                        )

                    if ts not in timestamped_data:
                        timestamped_data[ts] = {
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
                            for svc in target_services
                        }

                    if feature_name == "error_requests":
                        # Store temporary error requests
                        timestamped_data[ts][service]["_error_requests"] = value
                    elif feature_name == "request_rate":
                        timestamped_data[ts][service]["_total_requests"] = value
                        timestamped_data[ts][service]["request_rate"] = value
                    else:
                        timestamped_data[ts][service][feature_name] = value

        except Exception as e:
            logger.error(
                "Failed executing range query",
                feature=feature_name,
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                error=str(e),
                exc_info=True,
            )

    # Construct clean MetricWindow objects
    windows: list[MetricWindow] = []

    for ts, services_data in sorted(timestamped_data.items()):
        for service, features in services_data.items():
            # Calculate error rate from temporary counts
            errors = features.pop("_error_requests", 0.0)
            total = features.pop("_total_requests", 0.0)
            error_rate = 0.0
            if total > 0:
                error_rate = errors / total
            features["error_rate"] = error_rate

            # Construct window
            window = MetricWindow(
                service_name=service, timestamp=float(ts), feature_vector=features
            )
            windows.append(window)

    logger.info("Baseline data collection completed", total_datapoints=len(windows))
    return windows


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Collect baseline Prometheus metrics and train anomaly models."
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=30,
        help="Baseline collection window in minutes (default: 30)",
    )
    parser.add_argument(
        "--step", type=int, default=15, help="Query step interval in seconds (default: 15)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="checkpoints/isolation_forest.joblib",
        help="Model output file path",
    )
    parser.add_argument(
        "--seq-output",
        type=str,
        default="checkpoints/lstm_model.pt",
        help="Sequence forecaster model output file path",
    )
    args = parser.parse_args()

    scraper = PrometheusScraper()

    # Try fetching historical metrics
    windows = collect_historical_baseline(scraper, minutes=args.minutes, step_seconds=args.step)

    if not windows:
        logger.error(
            "No baseline data collected. Ensure Prometheus is running and scraping the services."
        )
        sys.exit(1)

    # Train the Isolation Forest models
    model = IsolationForestModel()
    model.fit(windows)
    model.save(args.output)

    # Train the sequence forecaster verification model
    seq_model = SequenceForecastModel()
    seq_model.fit(windows)
    seq_model.save(args.seq_output)
    logger.info(
        "Baseline model training completed successfully!",
        saved_path=args.output,
        seq_model_saved_path=args.seq_output,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
