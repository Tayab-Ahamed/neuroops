import os
from typing import Dict, List, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import structlog
from state import Alert, AgentState
from graph import graph

logger = structlog.get_logger()

app = FastAPI(title="NeuroOps Multi-Agent RCA API", version="1.0.0")

# Global dict to store incident trace reasoning history
incident_traces: Dict[str, List[Dict[str, Any]]] = {}

class RootCauseHypothesis(BaseModel):
    incident_id: str
    hypothesis: str
    confidence: float
    recommended_action: str
    requires_human_approval: bool
    reasoning: str

@app.post("/investigate", response_model=RootCauseHypothesis)
async def investigate(alert: Alert):
    """Triggers the multi-agent LangGraph workflow to diagnose a Kubernetes incident."""
    logger.info("Received alert for diagnostic investigation", alert_id=alert.id, service=alert.service)
    
    # Initialize the input state
    initial_state: AgentState = {
        "incident_id": "",
        "alert": alert,
        "detective_findings": None,
        "topologist_findings": None,
        "historian_findings": None,
        "hypothesis": None,
        "confidence": None,
        "recommended_action": None,
        "requires_human_approval": False
    }
    
    try:
        # Execute LangGraph workflow synchronously
        final_state = await graph.ainvoke(initial_state)
        
        incident_id = final_state.get("incident_id", "unknown")
        hypothesis = final_state.get("hypothesis") or "Unknown failure mode"
        confidence = final_state.get("confidence") or 0.0
        recommended_action = final_state.get("recommended_action") or "none"
        requires_human_approval = final_state.get("requires_human_approval") or False
        # Extract reasoning which is merged into the final state dict
        reasoning = final_state.get("reasoning") or "No detailed reasoning provided."
        
        # Save reasoning trace timeline
        trace_timeline = [
            {
                "step": 1,
                "agent": "supervisor_init",
                "action": "Initialized investigation and started OpenTelemetry root span.",
                "timestamp": alert.timestamp
            },
            {
                "step": 2,
                "agent": "detective",
                "findings": final_state.get("detective_findings"),
                "action": "Analyzed Prometheus metric correlations across cluster service endpoints."
            },
            {
                "step": 3,
                "agent": "topologist",
                "findings": final_state.get("topologist_findings"),
                "action": "Queried Jaeger trace dependency graphs to inspect latency bottlenecks."
            },
            {
                "step": 4,
                "agent": "historian",
                "findings": final_state.get("historian_findings"),
                "action": "Inspected GitHub commit logs and deployment timelines."
            },
            {
                "step": 5,
                "agent": "supervisor_synthesize",
                "action": "Fused multiple diagnostic findings into root cause hypothesis.",
                "hypothesis": hypothesis,
                "confidence": confidence,
                "recommended_action": recommended_action,
                "requires_human_approval": requires_human_approval,
                "reasoning": reasoning
            }
        ]
        incident_traces[incident_id] = trace_timeline
        
        logger.info(
            "Investigation completed successfully", 
            incident_id=incident_id, 
            hypothesis=hypothesis, 
            confidence=confidence
        )
        
        return RootCauseHypothesis(
            incident_id=incident_id,
            hypothesis=hypothesis,
            confidence=confidence,
            recommended_action=recommended_action,
            requires_human_approval=requires_human_approval,
            reasoning=reasoning
        )
    except Exception as e:
        logger.error("Failed executing RCA graph", error=str(e))
        raise HTTPException(status_code=500, detail=f"Diagnostic error: {str(e)}")

@app.get("/incidents/{incident_id}/trace", response_model=List[Dict[str, Any]])
async def get_incident_trace(incident_id: str):
    """Returns a step-by-step audit replay of the agent's reasoning steps for a given incident."""
    logger.info("Requesting incident trace", incident_id=incident_id)
    if incident_id not in incident_traces:
        raise HTTPException(status_code=404, detail=f"Incident trace for {incident_id} not found.")
        
    return incident_traces[incident_id]
