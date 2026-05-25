from typing import TypedDict, Dict, Optional, Any
from pydantic import BaseModel, Field

class Alert(BaseModel):
    id: str
    service: str
    severity: str
    timestamp: float
    metric_snapshot: Dict[str, float]
    anomaly_score: float

class AgentState(TypedDict):
    incident_id: str
    alert: Alert
    detective_findings: Optional[Dict[str, Any]]
    topologist_findings: Optional[Dict[str, Any]]
    historian_findings: Optional[Dict[str, Any]]
    log_findings: Optional[Dict[str, Any]]
    hypothesis: Optional[str]
    confidence: Optional[float]
    recommended_action: Optional[str]
    requires_human_approval: bool
