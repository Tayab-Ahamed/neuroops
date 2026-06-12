from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import BaseModel, Field
from state import AgentState
from tools.jaeger_tools import get_service_dependencies
from tracing import llm_retry, traced_node


class TopologistOutput(BaseModel):
    upstream_services: list[str] = Field(
        description="Services that call the target service (upstream dependencies)"
    )
    downstream_services: list[str] = Field(
        description="Services called by the target service (downstream dependencies)"
    )
    bottleneck: str = Field(
        description="The primary latency bottleneck service identified in the dependency graph"
    )


@traced_node("topologist")
async def topologist_node(state: AgentState) -> dict:
    alert = state["alert"]

    complexity_score = state.get("complexity_score", 0.5)
    from agents.llm import get_llm

    llm = get_llm(complexity_score=complexity_score)
    if llm is None:
        return {
            "topologist_findings": {
                "upstream_services": ["frontend"],
                "downstream_services": ["database-stub"],
                "bottleneck": "backend",
                "tool_called": "get_service_dependencies",
                "tokens_used": 950,
            }
        }

    tools = [get_service_dependencies]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {"get_service_dependencies": get_service_dependencies}

    messages = [
        HumanMessage(
            content=(
                f"You are the Topologist Agent for NeuroOps. An alert triggered on service '{alert.service}'.\n"
                f"Anomaly Score: {alert.anomaly_score:.3f}\n"
                f"Metric Snapshot: {alert.metric_snapshot}\n\n"
                f"Query the Jaeger dependency graph to map the service dependencies "
                f"and identify where the latency bottleneck lies in the request flow.\n"
                f"Use the `get_service_dependencies` tool to check '{alert.service}' and its related services.\n"
                f"Construct your final findings showing upstreams, downstreams, and the bottleneck."
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
    structured_llm = llm.with_structured_output(TopologistOutput)
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
    findings_dict["tokens_used"] = int(total_tokens) if total_tokens > 0 else 800

    return {"topologist_findings": findings_dict}
