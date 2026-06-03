import uuid

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from state import AgentState
from tracing import llm_retry, traced_node


class SupervisorOutput(BaseModel):
    hypothesis: str = Field(
        description="The synthesized root cause hypothesis detailing the diagnosed failure mode"
    )
    confidence: float = Field(
        description="Confidence rating from 0.0 to 1.0 indicating diagnostic certainty"
    )
    recommended_action: str = Field(
        description="The mapped remediation action from decision tree (rollback, restart, scale, none)"
    )
    requires_human_approval: bool = Field(
        description="Flag indicating if the action requires human operator review"
    )
    reasoning: str = Field(description="Step-by-step diagnostic reasoning synthesis")


@traced_node("supervisor_init")
async def supervisor_init_node(state: AgentState) -> dict:
    """Initializes the incident_id and begins the OTel tracing context."""
    incident_id = state.get("incident_id")
    if not incident_id:
        incident_id = f"inc-{str(uuid.uuid4())[:8]}"

    return {"incident_id": incident_id, "requires_human_approval": False}


@traced_node("supervisor_synthesize")
async def supervisor_synthesize_node(state: AgentState) -> dict:
    """Synthesizes findings from Detective, Topologist, Historian, and Log Triage nodes to form a Root Cause Hypothesis."""
    alert = state["alert"]
    detective = state.get("detective_findings") or {}
    topologist = state.get("topologist_findings") or {}
    historian = state.get("historian_findings") or {}
    logs = state.get("log_findings") or {}

    from agents.llm import get_llm

    llm = get_llm()
    if llm is None:
        # Synthesize logic based on mock inputs
        suspect = historian.get("suspect_commit")
        action = "none"
        confidence = 0.5
        requires_human = True

        if suspect:
            action = "rollback"
            confidence = 0.85
            requires_human = True
        elif alert.service == "backend":
            action = "restart"
            confidence = 0.70
            requires_human = False

        return {
            "hypothesis": f"Anomaly on '{alert.service}' caused by bottleneck in '{topologist.get('bottleneck')}' and suspect commit '{suspect}'. Logs show: {logs.get('suspect_stack_trace', 'none')}",
            "confidence": confidence,
            "recommended_action": action,
            "requires_human_approval": requires_human,
            "reasoning": f"Synthesized reasoning: Detective blamed '{detective.get('likely_origin')}', Topologist saw bottleneck '{topologist.get('bottleneck')}', Historian flagged commit '{suspect}', Logs flagged '{logs.get('reasoning')}'.",
            "tool_called": "none",
            "tokens_used": 1500,
        }

    messages = [
        HumanMessage(
            content=(
                f"You are the Supervisor Agent for NeuroOps. Review the following RCA inputs:\n\n"
                f"1. ALERT INFO:\n"
                f"Service: {alert.service}\n"
                f"Severity: {alert.severity}\n"
                f"Anomaly Score: {alert.anomaly_score:.3f}\n"
                f"Snapshot: {alert.metric_snapshot}\n\n"
                f"2. DETECTIVE FINDINGS (Metric Correlation):\n"
                f"{detective}\n\n"
                f"3. TOPOLOGIST FINDINGS (Jaeger Dependency):\n"
                f"{topologist}\n\n"
                f"4. HISTORIAN FINDINGS (GitHub Deployments):\n"
                f"{historian}\n\n"
                f"5. LOG TRIAGE FINDINGS (Container Logs):\n"
                f"{logs}\n\n"
                f"Synthesize this diagnostic information into a Root Cause Hypothesis.\n"
                f"Refer to the Remediation Decision Tree:\n"
                f"- If there's a recent suspect commit within last 60 minutes and service is failing/restarting: Recommend 'rollback'\n"
                f"- If high CPU/OOMKill/Memory saturation: Recommend 'scale' or 'restart'\n"
                f"- If log findings show database deadlocks or query failures: Recommend 'restart' or 'scale'\n"
                f"- Destructive actions (like rollback) always require human approval (requires_human_approval = True)\n"
                f"- If confidence < 0.6: Set recommended_action to 'none', requires_human_approval = True\n\n"
                f"Emit the final synthesized findings structured schema."
            )
        )
    ]

    structured_llm = llm.with_structured_output(SupervisorOutput)
    findings = await llm_retry(structured_llm.ainvoke)(messages)

    return {
        "hypothesis": findings.hypothesis,
        "confidence": findings.confidence,
        "recommended_action": findings.recommended_action,
        "requires_human_approval": findings.requires_human_approval,
        "reasoning": findings.reasoning,
        "tool_called": "none",
        "tokens_used": 1100,
    }
