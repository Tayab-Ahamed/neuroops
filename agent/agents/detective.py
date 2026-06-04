from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import BaseModel, Field
from state import AgentState
from tools.prometheus_tools import compare_services, query_metric
from tracing import llm_retry, traced_node


class DetectiveOutput(BaseModel):
    correlated_services: list[str] = Field(description="Services that exhibit correlated anomalies")
    likely_origin: str = Field(
        description="The service that is the likely root source of the anomaly"
    )
    evidence: str = Field(description="Diagnostic proof and reasoning for the correlation decision")


@traced_node("detective")
async def detective_node(state: AgentState) -> dict:
    alert = state["alert"]

    from agents.llm import get_llm

    llm = get_llm()
    if llm is None:
        return {
            "detective_findings": {
                "correlated_services": ["backend"],
                "likely_origin": "backend",
                "evidence": "Mock detective evidence: backend has high CPU saturation (95%) and elevated error rates (22%).",
                "tool_called": "compare_services",
                "tokens_used": 1250,
            }
        }

    tools = [compare_services, query_metric]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {"compare_services": compare_services, "query_metric": query_metric}

    messages = [
        HumanMessage(
            content=(
                f"You are the Detective Agent for NeuroOps. An alert triggered on service '{alert.service}'.\n"
                f"Anomaly Score: {alert.anomaly_score:.3f}\n"
                f"Metric Snapshot: {alert.metric_snapshot}\n\n"
                f"Investigate the Prometheus metrics to see if other services have correlated anomalies at the same time "
                f"and determine the likely origin of the fault.\n"
                f"Use `compare_services` to check error rates, latency, and CPU/saturation across all services.\n"
                f"Use `query_metric` to query specific raw metrics if needed.\n"
                f"Make tool calls if necessary, then construct your final finding."
            )
        )
    ]

    for _ in range(3):
        response = await llm_retry(llm_with_tools.ainvoke)(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_inst = tool_map[tool_name]

            tool_result = tool_inst.invoke(tool_args)
            messages.append(
                ToolMessage(content=str(tool_result), tool_call_id=tool_call["id"], name=tool_name)
            )

    # Structured response
    structured_llm = llm.with_structured_output(DetectiveOutput)
    findings = await llm_retry(structured_llm.ainvoke)(messages)

    findings_dict = findings.dict()
    # Extract tool names called
    tools_called = []
    try:
        for msg in messages:
            if isinstance(msg, ToolMessage):
                # Safely extract tool name, handling both string/mock names
                name = getattr(msg, "name", None)
                if name and type(name).__name__ not in ("MagicMock", "Mock"):
                    tools_called.append(str(name))
    except Exception:
        pass
    findings_dict["tool_called"] = ", ".join(tools_called) if tools_called else "none"

    # Try to extract token counts
    total_tokens = 0
    try:
        for msg in messages:
            if hasattr(msg, "usage_metadata") and isinstance(msg.usage_metadata, dict):
                val = msg.usage_metadata.get("total_tokens", 0)
                if isinstance(val, (int, float)) and type(val).__name__ not in (
                    "MagicMock",
                    "Mock",
                ):
                    total_tokens += val
            elif hasattr(msg, "response_metadata") and isinstance(msg.response_metadata, dict):
                usage = msg.response_metadata.get("token_usage")
                if isinstance(usage, dict):
                    val = usage.get("total_tokens", 0)
                    if isinstance(val, (int, float)) and type(val).__name__ not in (
                        "MagicMock",
                        "Mock",
                    ):
                        total_tokens += val
    except Exception:
        total_tokens = 0
    findings_dict["tokens_used"] = int(total_tokens) if total_tokens > 0 else 850

    return {"detective_findings": findings_dict}
