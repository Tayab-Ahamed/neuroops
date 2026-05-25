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
    """Stub node for remediation action mapping in subsequent phases."""
    logger.info("Incident routed to remediation engine", incident_id=state.get("incident_id"))
    return {"requires_human_approval": False}

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
