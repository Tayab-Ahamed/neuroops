import uuid
import time
from typing import Dict, Optional
from pydantic import BaseModel, Field
import structlog
from scraper import MetricWindow

logger = structlog.get_logger()

class Alert(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    service: str
    severity: str
    timestamp: float
    metric_snapshot: Dict[str, float]
    anomaly_score: float

class Alerter:
    def __init__(self, deduplication_window_seconds: float = 300.0):
        self.deduplication_window = deduplication_window_seconds
        # service_name -> last alert timestamp
        self.last_alerted: Dict[str, float] = {}
        logger.info("Initialized Alerter", deduplication_window=deduplication_window_seconds)

    def process_window(self, window: MetricWindow, anomaly_score: float, is_anomaly: bool) -> Optional[Alert]:
        """Processes a MetricWindow and generates a deduplicated Alert if anomalous."""
        if not is_anomaly:
            return None

        service = window.service_name
        current_time = time.time()
        
        # 1. Deduplication check
        last_alert_time = self.last_alerted.get(service, 0.0)
        time_since_last_alert = current_time - last_alert_time
        
        if time_since_last_alert < self.deduplication_window:
            logger.info(
                "Alert suppressed due to deduplication", 
                service=service, 
                time_since_last_alert=time_since_last_alert,
                deduplication_window=self.deduplication_window
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
            anomaly_score=anomaly_score
        )

        # Update last alerted timestamp for deduplication (only for P1/P2, or all alerts)
        # Suppress alerts for the same service within 5 minutes (standard behavior for all fired alerts)
        self.last_alerted[service] = current_time
        
        logger.info(
            "New alert classified and fired", 
            id=alert.id,
            service=service, 
            severity=severity, 
            anomaly_score=anomaly_score,
            error_rate=error_rate,
            pod_restarts=pod_restarts
        )
        return alert
