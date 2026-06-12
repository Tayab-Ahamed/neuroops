import math
import threading
import time
import uuid

import structlog
from pydantic import BaseModel, Field
from scraper import MetricWindow

logger = structlog.get_logger()


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    service: str
    severity: str
    timestamp: float
    metric_snapshot: dict[str, float]
    anomaly_score: float
    type: str = "reactive"
    metric: str | None = None
    current_value: float | None = None
    predicted_value: float | None = None
    time_to_breach_seconds: float | None = None
    confidence: float | None = None


class Alerter:
    def __init__(self, deduplication_window_seconds: float = 300.0):
        self.deduplication_window = deduplication_window_seconds
        # service_name -> last alert timestamp
        self.last_alerted: dict[str, float] = {}
        self._dedup_lock = threading.Lock()
        self._issued_alert_ids: set[str] = set()
        logger.info("Initialized Alerter", deduplication_window=deduplication_window_seconds)

    def process_window(
        self, window: MetricWindow, anomaly_score: float, is_anomaly: bool
    ) -> Alert | None:
        """Processes a MetricWindow and generates a deduplicated Alert if anomalous."""
        if not is_anomaly:
            return None

        if anomaly_score is None or math.isnan(anomaly_score):
            logger.warning(
                "Skipping alert creation due to invalid anomaly score",
                service=window.service_name,
                timestamp=window.timestamp,
                anomaly_score=anomaly_score,
            )
            return None

        service = window.service_name
        current_time = time.time()

        # 1. Deduplication check
        with self._dedup_lock:
            last_alert_time = self.last_alerted.get(service, 0.0)
            time_since_last_alert = current_time - last_alert_time

            if time_since_last_alert < self.deduplication_window:
                logger.info(
                    "Alert suppressed due to deduplication",
                    service=service,
                    timestamp=window.timestamp,
                    time_since_last_alert=time_since_last_alert,
                    deduplication_window=self.deduplication_window,
                )
                return None

        # 2. Severity classification
        error_rate = window.feature_vector.get("error_rate", 0.0)
        pod_restarts = window.feature_vector.get("pod_restarts", 0.0)

        # P1: anomaly score < -0.5 AND (error_rate > 0.1 OR pod_restarts > 3)
        if anomaly_score < -0.5 and (error_rate > 0.1 or pod_restarts > 3):
            severity = "P1"
        # P2: anomaly score < -0.3
        elif anomaly_score < -0.3:
            severity = "P2"
        # P3: everything else
        else:
            severity = "P3"

        # 3. Create Alert
        alert = Alert(
            service=service,
            severity=severity,
            timestamp=current_time,
            metric_snapshot=window.feature_vector,
            anomaly_score=anomaly_score,
        )
        self.ensure_unique_alert_id(alert)

        # Update last alerted timestamp for deduplication (only for P1/P2, or all alerts)
        # Suppress alerts for the same service within 5 minutes (standard behavior for all fired alerts)
        with self._dedup_lock:
            self.last_alerted[service] = current_time

        logger.info(
            "New alert classified and fired",
            id=alert.id,
            service=service,
            severity=severity,
            anomaly_score=anomaly_score,
            error_rate=error_rate,
            pod_restarts=pod_restarts,
        )
        return alert

    def ensure_unique_alert_id(
        self, alert: Alert, active_alerts: list[Alert] | None = None
    ) -> None:
        """Regenerates the alert ID if it collides with already issued or active alerts."""
        active_ids = {existing.id for existing in active_alerts or []}
        with self._dedup_lock:
            while alert.id in active_ids or (
                active_alerts is None and alert.id in self._issued_alert_ids
            ):
                logger.warning(
                    "Alert ID collision detected; regenerating alert ID",
                    collided_id=alert.id,
                    service=alert.service,
                    timestamp=alert.timestamp,
                )
                alert.id = str(uuid.uuid4())
            self._issued_alert_ids.add(alert.id)
