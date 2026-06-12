import os
import uuid

import structlog
from langchain_core.messages import HumanMessage
from memory import IncidentMemory, extract_metric_vector
from pydantic import BaseModel, Field
from state import AgentState
from tracing import llm_retry, traced_node

logger = structlog.get_logger()


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


def compute_complexity(state: AgentState) -> float:
    score = 0.0
    detective = state.get("detective_findings") or {}
    correlated_services = detective.get("correlated_services") or []
    score += 0.2 * min(len(correlated_services), 3)

    alert = state.get("alert")
    if alert:
        if alert.severity == "P1":
            score += 0.1
        elif alert.severity == "P2":
            score += 0.3
        score += min(abs(alert.anomaly_score) * 0.4, 0.4)

    return min(score, 1.0)


@traced_node("supervisor_init")
async def supervisor_init_node(state: AgentState) -> dict:
    """Initializes the incident_id and begins the OTel tracing context."""
    incident_id = state.get("incident_id")
    if not incident_id:
        incident_id = f"inc-{str(uuid.uuid4())[:8]}"

    complexity_score = compute_complexity(state)
    return {
        "incident_id": incident_id,
        "requires_human_approval": False,
        "complexity_score": complexity_score,
    }


@traced_node("supervisor_synthesize")
async def supervisor_synthesize_node(state: AgentState) -> dict:
    """Synthesizes findings from Detective, Topologist, Historian, and Log Triage nodes to form a Root Cause Hypothesis."""
    alert = state["alert"]
    detective = state.get("detective_findings") or {}
    topologist = state.get("topologist_findings") or {}
    historian = state.get("historian_findings") or {}
    logs = state.get("log_findings") or {}

    memory = IncidentMemory()
    metric_vector = extract_metric_vector(alert.metric_snapshot)
    similar_incidents = memory.retrieve_similar(metric_vector, top_k=3)

    complexity_score = state.get("complexity_score", 0.5)
    from agents.llm import get_llm

    llm = get_llm(complexity_score=complexity_score)
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

        auto_threshold = float(os.getenv("AUTONOMOUS_CONFIDENCE_THRESHOLD", "0.65"))
        safe_actions = {"restart_pod", "restart", "scale_replicas", "scale", "none"}
        if action in safe_actions and confidence >= auto_threshold:
            requires_human = False

        return {
            "hypothesis": f"Anomaly on '{alert.service}' caused by bottleneck in '{topologist.get('bottleneck')}' and suspect commit '{suspect}'. Logs show: {logs.get('suspect_stack_trace', 'none')}",
            "confidence": confidence,
            "recommended_action": action,
            "requires_human_approval": requires_human,
            "reasoning": f"Synthesized reasoning: Detective blamed '{detective.get('likely_origin')}', Topologist saw bottleneck '{topologist.get('bottleneck')}', Historian flagged commit '{suspect}', Logs flagged '{logs.get('reasoning')}'.",
            "tool_called": "none",
            "tokens_used": 1500,
            "similar_incidents": similar_incidents,
        }

    context_str = ""
    if similar_incidents:
        formatted = "\n".join(
            [
                f"- Incident ID: {inc['incident_id']} (Similarity Score: {inc['similarity_score']:.4f})\n"
                f"  Hypothesis: {inc['hypothesis']}\n"
                f"  Action: {inc['action']}\n"
                f"  Outcome: {inc['outcome']}"
                for inc in similar_incidents
            ]
        )
        context_str = f"Similar past resolved incidents for context:\n{formatted}\n\n"

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
                f"{context_str}"
                f"Synthesize this diagnostic information into a Root Cause Hypothesis.\n"
                f"Refer to the Remediation Decision Tree:\n"
                f"- If there is a recent suspect commit within last 60 minutes AND confidence >= 0.65: Recommend 'rollback', requires_human_approval = True (rollback is always destructive)\n"
                f"- If high CPU/OOMKill/Memory saturation, pod restarts, or CrashLoopBackOff in logs: Recommend 'restart_pod' or 'scale_replicas'\n"
                f"- If log findings show database deadlocks or query failures: Recommend 'restart_pod' or 'scale_replicas'\n"
                f"- If recommended_action is 'restart_pod' or 'scale_replicas' AND confidence >= 0.65: Set requires_human_approval = False\n"
                f"- If confidence < 0.55: Set recommended_action to 'none', requires_human_approval = True\n"
                f"- Chaos experiment signatures (LitmusChaos, pod-delete, cpu-hog, memory-hog, network-latency, disk-fill) in any finding are strong evidence — treat them as high-confidence even if other signals are weak\n\n"
                f"Emit the final synthesized findings structured schema."
            )
        )
    ]

    structured_llm = llm.with_structured_output(SupervisorOutput)
    findings = await llm_retry(structured_llm.ainvoke)(messages)

    # ── Post-LLM confidence adjustment ──────────────────────────────────
    # Boost confidence when chaos experiment signatures are clearly identified
    CHAOS_SIGNATURES = [
        "chaos",
        "oomkill",
        "oOMKill",
        "cpu-hog",
        "memory-hog",
        "pod-delete",
        "network-latency",
        "disk-fill",
        "crashloopbackoff",
        "litmuschaos",
        "CrashLoopBackOff",
        "OOMKilled",
    ]
    auto_threshold = float(os.getenv("AUTONOMOUS_CONFIDENCE_THRESHOLD", "0.65"))
    hyp_lower = findings.hypothesis.lower()
    reasoning_lower = findings.reasoning.lower()
    if any(sig.lower() in hyp_lower or sig.lower() in reasoning_lower for sig in CHAOS_SIGNATURES):

        if findings.confidence < auto_threshold + 0.07:
            boosted = min(findings.confidence + 0.08, 1.0)
            logger.info(
                "Confidence boosted due to chaos signature evidence",
                original=findings.confidence,
                boosted=boosted,
            )
            findings = findings.model_copy(update={"confidence": boosted})

    # Override requires_human_approval based on final confidence + action safety
    safe_actions = {"restart_pod", "restart", "scale_replicas", "scale", "none"}
    if findings.recommended_action in safe_actions and findings.confidence >= auto_threshold:
        findings = findings.model_copy(update={"requires_human_approval": False})

    return {
        "hypothesis": findings.hypothesis,
        "confidence": findings.confidence,
        "recommended_action": findings.recommended_action,
        "requires_human_approval": findings.requires_human_approval,
        "reasoning": findings.reasoning,
        "tool_called": "none",
        "tokens_used": 1100,
        "similar_incidents": similar_incidents,
    }
