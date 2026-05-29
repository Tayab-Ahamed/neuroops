import os
import httpx
import structlog
from langgraph.graph import StateGraph, START, END
from state import AgentState
from agents.supervisor import supervisor_init_node, supervisor_synthesize_node
from agents.detective import detective_node
from agents.topologist import topologist_node
from agents.historian import historian_node
from agents.log_analyser import log_analyser_node
from tracing import traced_node

logger = structlog.get_logger()

@traced_node("human_escalation")
async def human_escalation_node(state: AgentState) -> dict:
    """Escalates the incident to human SRE operators due to low confidence or high risk."""
    logger.warning("Incident diagnosis escalated to human operator", incident_id=state.get("incident_id"))
    return {"requires_human_approval": True}

@traced_node("remediator")
async def remediator_node(state: AgentState) -> dict:
    """Optionally dispatches remediation to the remediator service."""
    incident_id = state.get("incident_id")
    logger.info("Incident routed to remediation engine", incident_id=incident_id)

    if not state.get("execute_remediation"):
        return {
            "requires_human_approval": False,
            "remediation_result": {
                "status": "planned",
                "message": "Remediation execution disabled for this investigation request.",
            },
        }

    remediator_url = os.getenv("REMEDIATOR_URL", "http://localhost:8003")
    payload = {
        "incident_id": incident_id,
        "hypothesis": state.get("hypothesis") or "Unknown failure mode",
        "confidence": state.get("confidence") or 0.0,
        "recommended_action": state.get("recommended_action") or "none",
        "requires_human_approval": state.get("requires_human_approval") or False,
        "reasoning": state.get("reasoning") or "No reasoning provided.",
        "alert": state["alert"].model_dump(),
    }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{remediator_url}/remediate", json=payload)
        response.raise_for_status()
        return {
            "requires_human_approval": bool(payload["requires_human_approval"]),
            "remediation_result": response.json(),
        }
    except Exception as exc:
        logger.warning(
            "Remediation dispatch failed, falling back to planned response",
            incident_id=incident_id,
            error=str(exc),
        )
        return {
            "requires_human_approval": True,
            "remediation_result": {
                "status": "dispatch_failed",
                "message": str(exc),
            },
        }

def route_based_on_confidence(state: AgentState) -> str:
    """Routes execution flow based on diagnostic confidence and safety thresholds."""
    confidence = state.get("confidence") or 0.0
    requires_human = state.get("requires_human_approval") or False
    
    logger.info("Routing decision", confidence=confidence, requires_human_approval=requires_human)
    if confidence < 0.6 or requires_human:
        return "escalate"
        
    return "remediate"

# Assemble the StateGraph workflow
workflow = StateGraph(AgentState)

# Add all diagnostic and routing nodes
workflow.add_node("supervisor_init", supervisor_init_node)
workflow.add_node("detective", detective_node)
workflow.add_node("topologist", topologist_node)
workflow.add_node("historian", historian_node)
workflow.add_node("log_analyser", log_analyser_node)
workflow.add_node("supervisor_synthesize", supervisor_synthesize_node)
workflow.add_node("human_escalation", human_escalation_node)
workflow.add_node("remediator", remediator_node)

# Set starting edge
workflow.add_edge(START, "supervisor_init")

# Fan-out from supervisor initialization to parallel diagnosis agents
workflow.add_edge("supervisor_init", "detective")
workflow.add_edge("supervisor_init", "topologist")
workflow.add_edge("supervisor_init", "historian")
workflow.add_edge("supervisor_init", "log_analyser")

# Fan-in from diagnosis agents to the synthesis supervisor
workflow.add_edge("detective", "supervisor_synthesize")
workflow.add_edge("topologist", "supervisor_synthesize")
workflow.add_edge("historian", "supervisor_synthesize")
workflow.add_edge("log_analyser", "supervisor_synthesize")

# Conditional edge based on LLM confidence and approval flags
workflow.add_conditional_edges(
    "supervisor_synthesize",
    route_based_on_confidence,
    {
        "escalate": "human_escalation",
        "remediate": "remediator"
    }
)

# Connect stubs to END node
workflow.add_edge("human_escalation", END)
workflow.add_edge("remediator", END)

# Compile LangGraph with in-memory checkpointer for persistence
from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
graph = workflow.compile(checkpointer=memory)
