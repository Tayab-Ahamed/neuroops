import os
import time
from collections import deque

import numpy as np
import structlog
from alerter import Alert
from scraper import MetricWindow

logger = structlog.get_logger()


class PreFaultAlert(Alert):
    type: str = "predictive"
    severity: str = "P3"
    anomaly_score: float = 0.0
    metric: str
    current_value: float
    predicted_value: float
    time_to_breach_seconds: float
    confidence: float


class TrendForecaster:
    def __init__(self) -> None:
        self.buffers: dict[str, deque[MetricWindow]] = {}
        self.last_alerted: dict[tuple[str, str], float] = {}
        logger.info("Initialized TrendForecaster")

    def update(self, window: MetricWindow) -> None:
        service = window.service_name
        if service not in self.buffers:
            self.buffers[service] = deque(maxlen=120)
        self.buffers[service].append(window)

    def predict_breach(self, service: str, horizon_steps: int = 20) -> PreFaultAlert | None:
        history = self.buffers.get(service)
        if not history or len(history) < 5:
            return None

        # Subtract timestamps[0] to avoid numerical precision errors in polyfit
        timestamps = [w.timestamp for w in history]
        t0 = timestamps[0]
        x = np.array([t - t0 for t in timestamps], dtype=np.float64)

        # Get SLO thresholds from env vars or defaults
        slo_p99_latency_ms = float(os.getenv("SLO_P99_LATENCY_MS", "500"))
        slo_error_rate = float(os.getenv("SLO_ERROR_RATE", "0.05"))
        slo_cpu_pct = float(os.getenv("SLO_CPU_PCT", "85"))
        slo_memory_pct = float(os.getenv("SLO_MEMORY_PCT", "90"))

        detected_breaches = []

        for metric_name in ["p99_latency", "error_rate", "cpu_usage", "memory_usage"]:
            y = np.array(
                [w.feature_vector.get(metric_name, 0.0) for w in history], dtype=np.float64
            )

            # Perform degree 1 polyfit
            with np.errstate(all="ignore"):
                slope, intercept = np.polyfit(x, y, 1)

            # Extrapolate horizon_steps forward (1 step = 15s)
            latest_x = x[-1]
            horizon_x = latest_x + (horizon_steps * 15.0)
            predicted_val = slope * horizon_x + intercept

            # R2 (Coefficient of Determination)
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1.0 - (ss_res / ss_tot) if ss_tot != 0.0 else 1.0
            r_squared = max(0.0, min(1.0, r_squared))

            # Units mapping & conversion
            latest_val = y[-1]
            if metric_name == "p99_latency":
                current_val_scaled = latest_val * 1000.0
                predicted_val_scaled = predicted_val * 1000.0
                threshold_scaled = slo_p99_latency_ms
                threshold_unscaled = slo_p99_latency_ms / 1000.0
            elif metric_name == "error_rate":
                current_val_scaled = latest_val
                predicted_val_scaled = predicted_val
                threshold_scaled = slo_error_rate
                threshold_unscaled = slo_error_rate
            elif metric_name == "cpu_usage":
                current_val_scaled = latest_val * 100.0
                predicted_val_scaled = predicted_val * 100.0
                threshold_scaled = slo_cpu_pct
                threshold_unscaled = slo_cpu_pct / 100.0
            elif metric_name == "memory_usage":
                # Max limit: 128Mi = 134217728.0 bytes
                current_val_scaled = (latest_val / 134217728.0) * 100.0
                predicted_val_scaled = (predicted_val / 134217728.0) * 100.0
                threshold_scaled = slo_memory_pct
                threshold_unscaled = (slo_memory_pct / 100.0) * 134217728.0
            else:
                continue

            # Compare against SLO threshold and ensure confidence fits
            if predicted_val_scaled > threshold_scaled and r_squared > 0.70:
                if slope > 0:
                    time_to_breach = (threshold_unscaled - intercept) / slope - latest_x
                    if time_to_breach < 0:
                        time_to_breach = 0.0
                else:
                    time_to_breach = 0.0

                detected_breaches.append(
                    {
                        "metric": metric_name,
                        "current_value": round(current_val_scaled, 4),
                        "predicted_value": round(predicted_val_scaled, 4),
                        "time_to_breach_seconds": round(time_to_breach, 2),
                        "confidence": round(r_squared, 4),
                    }
                )

        if not detected_breaches:
            return None

        # Sort breaches by time to breach ascending (earliest first)
        detected_breaches.sort(key=lambda b: b["time_to_breach_seconds"])
        breach = detected_breaches[0]

        # Deduplication: suppress if alerted in the last 300s
        current_time = time.time()
        metric_key = breach["metric"]
        last_alert_time = self.last_alerted.get((service, metric_key), 0.0)
        if current_time - last_alert_time < 300.0:
            logger.info(
                "Predictive alert suppressed due to deduplication",
                service=service,
                metric=metric_key,
                time_since_last_alert=current_time - last_alert_time,
            )
            return None

        # Record alert time and create PreFaultAlert
        self.last_alerted[(service, metric_key)] = current_time

        logger.info(
            "Predictive alert generated",
            service=service,
            metric=metric_key,
            current_value=breach["current_value"],
            predicted_value=breach["predicted_value"],
            time_to_breach_seconds=breach["time_to_breach_seconds"],
            confidence=breach["confidence"],
        )

        return PreFaultAlert(
            service=service,
            metric=metric_key,
            current_value=breach["current_value"],
            predicted_value=breach["predicted_value"],
            time_to_breach_seconds=breach["time_to_breach_seconds"],
            confidence=breach["confidence"],
            timestamp=current_time,
            metric_snapshot=history[-1].feature_vector,
            anomaly_score=0.0,
        )
