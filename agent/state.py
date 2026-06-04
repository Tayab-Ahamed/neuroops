from typing import Any, TypedDict

from pydantic import BaseModel


class Alert(BaseModel):
    id: str
    service: str
    severity: str
    timestamp: float
    metric_snapshot: dict[str, float]
    anomaly_score: float


class AgentState(TypedDict):
    incident_id: str
    alert: Alert
    detective_findings: dict[str, Any] | None
    topologist_findings: dict[str, Any] | None
    historian_findings: dict[str, Any] | None
    log_findings: dict[str, Any] | None
    hypothesis: str | None
    confidence: float | None
    recommended_action: str | None
    requires_human_approval: bool
    reasoning: str | None
    tokens_used: int | None
    execute_remediation: bool
    remediation_result: dict[str, Any] | None
    similar_incidents: list[dict]
