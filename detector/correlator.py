"""
detector/correlator.py — Alert Correlation Engine for NeuroOps

Groups alerts that fire within a configurable time window into correlated
CorrelatedAlert objects. Prevents the LangGraph multi-agent RCA pipeline
from being triggered redundantly for simultaneous cross-service failures.
"""
import time
import uuid
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import structlog

logger = structlog.get_logger()


class Alert(BaseModel):
    id: str
    service: str
    severity: str
    timestamp: float
    metric_snapshot: Dict[str, float]
    anomaly_score: float


class CorrelatedAlert(BaseModel):
    correlation_id: str = Field(description="Unique ID for this correlated alert group")
    alerts: List[Alert] = Field(description="All alerts in this correlation group")
    primary_service: str = Field(description="The service with the worst anomaly score")
    severity: str = Field(description="Highest severity level across the group")
    first_seen: float = Field(description="Timestamp of the earliest alert in group")
    last_seen: float = Field(description="Timestamp of the latest alert in group")
    affected_services: List[str] = Field(description="All unique service names in group")
    correlation_window_seconds: float = Field(
        default=30.0, description="Time window used to correlate alerts"
    )
    is_cascading_failure: bool = Field(
        default=False,
        description="True if multiple services are affected (likely cascading failure)"
    )


class AlertCorrelator:
    """
    Correlates alerts that fire within a sliding time window.

    Algorithm:
    1. Maintains a rolling buffer of recent alerts (max_age_seconds)
    2. Groups alerts that are within `correlation_window_seconds` of each other
    3. Within each group, selects the primary_service as the one with the worst anomaly_score
    4. Flags groups with > 1 unique service as `is_cascading_failure = True`
    """

    def __init__(
        self,
        correlation_window_seconds: float = 30.0,
        max_age_seconds: float = 300.0,
    ):
        self.correlation_window_seconds = correlation_window_seconds
        self.max_age_seconds = max_age_seconds
        # Internal buffer of all raw alerts within max_age window
        self._alert_buffer: List[Alert] = []

    def _severity_rank(self, severity: str) -> int:
        """Returns numeric rank for severity comparison (lower = more severe)."""
        return {"P1": 1, "P2": 2, "P3": 3}.get(severity.upper(), 99)

    def ingest(self, alerts: List[Alert]) -> None:
        """Ingests new alerts into the correlation buffer, pruning stale ones."""
        now = time.time()
        cutoff = now - self.max_age_seconds

        # Prune stale alerts
        self._alert_buffer = [a for a in self._alert_buffer if a.timestamp >= cutoff]

        # Add new alerts (deduplicate by id)
        existing_ids = {a.id for a in self._alert_buffer}
        for alert in alerts:
            if alert.id not in existing_ids:
                self._alert_buffer.append(alert)
                existing_ids.add(alert.id)

        logger.info(
            "Alert correlator buffer updated",
            buffer_size=len(self._alert_buffer),
            new_alerts=len([a for a in alerts if a.id not in existing_ids]),
        )

    def correlate(self) -> List[CorrelatedAlert]:
        """
        Groups buffered alerts into correlated groups using a greedy sliding window.

        Returns:
            List of CorrelatedAlert objects, sorted by severity (P1 first).
        """
        if not self._alert_buffer:
            return []

        # Sort alerts by timestamp ascending
        sorted_alerts = sorted(self._alert_buffer, key=lambda a: a.timestamp)

        groups: List[List[Alert]] = []
        current_group: List[Alert] = []

        for alert in sorted_alerts:
            if not current_group:
                current_group.append(alert)
            else:
                # Check if this alert is within the window of the earliest alert in the group
                group_start = current_group[0].timestamp
                if alert.timestamp - group_start <= self.correlation_window_seconds:
                    current_group.append(alert)
                else:
                    groups.append(current_group)
                    current_group = [alert]

        if current_group:
            groups.append(current_group)

        correlated: List[CorrelatedAlert] = []
        for group in groups:
            if not group:
                continue

            # Find primary service (worst anomaly score — most negative)
            primary = min(group, key=lambda a: a.anomaly_score)
            # Find highest severity
            best_sev = min(group, key=lambda a: self._severity_rank(a.severity))
            affected = list({a.service for a in group})

            correlated_alert = CorrelatedAlert(
                correlation_id=f"corr-{str(uuid.uuid4())[:8]}",
                alerts=group,
                primary_service=primary.service,
                severity=best_sev.severity,
                first_seen=group[0].timestamp,
                last_seen=group[-1].timestamp,
                affected_services=affected,
                correlation_window_seconds=self.correlation_window_seconds,
                is_cascading_failure=len(affected) > 1,
            )
            correlated.append(correlated_alert)
            logger.info(
                "Correlated alert group created",
                correlation_id=correlated_alert.correlation_id,
                services=affected,
                is_cascading=correlated_alert.is_cascading_failure,
                severity=correlated_alert.severity,
            )

        # Sort by severity (P1 first), then by recency
        correlated.sort(key=lambda c: (self._severity_rank(c.severity), -c.last_seen))
        return correlated

    def get_correlation_stats(self) -> Dict:
        """Returns statistics about the current correlation state."""
        correlated = self.correlate()
        cascading = [c for c in correlated if c.is_cascading_failure]
        return {
            "total_buffered_alerts": len(self._alert_buffer),
            "correlated_groups": len(correlated),
            "cascading_failure_groups": len(cascading),
            "correlation_window_seconds": self.correlation_window_seconds,
            "max_age_seconds": self.max_age_seconds,
        }
