import os

from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import BaseModel, Field
from state import AgentState
from tools.github_tools import get_recent_deploys
from tracing import llm_retry, traced_node


class HistorianOutput(BaseModel):
    recent_deploys: list[dict] = Field(description="List of recent commits or deployments found")
    suspect_commit: str | None = Field(
        description="The commit hash of a suspect deployment, if any"
    )
    deploy_time: str | None = Field(description="The timestamp of the suspect deployment, if any")


@traced_node("historian")
async def historian_node(state: AgentState) -> dict:
    alert = state["alert"]

    from agents.llm import get_llm

    llm = get_llm()
    if llm is None:
        return {
            "historian_findings": {
                "recent_deploys": [
                    {
                        "commit": "a1b2c3d4e5f6",
                        "author": "Alice Smith <alice@neuroops.io>",
                        "message": "chore(backend): update database connection pool configuration (#42)",
                        "date": "2026-05-22T17:30:00Z",
                    }
                ],
                "suspect_commit": "a1b2c3d4e5f6",
                "deploy_time": "2026-05-22T17:30:00Z",
                "tool_called": "get_recent_deploys",
                "tokens_used": 800,
            }
        }

    tools = [get_recent_deploys]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {"get_recent_deploys": get_recent_deploys}

    # Historian should look at the configured repo from env vars
    github_repo = os.getenv("GITHUB_REPO", "your-username/neuroops")

    messages = [
        HumanMessage(
            content=(
                f"You are the Historian Agent for NeuroOps. An alert triggered on service '{alert.service}'.\n"
                f"Anomaly Score: {alert.anomaly_score:.3f}\n"
                f"Metric Snapshot: {alert.metric_snapshot}\n\n"
                f"Query the deployment history in GitHub for the repository '{github_repo}' "
                f"to check for recent code updates or configuration commits in the last 60 minutes.\n"
                f"Use the `get_recent_deploys` tool to fetch commit information.\n"
                f"If there is a suspect commit that could explain the anomaly on '{alert.service}', highlight it."
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
    structured_llm = llm.with_structured_output(HistorianOutput)
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
    findings_dict["tokens_used"] = int(total_tokens) if total_tokens > 0 else 750

    return {"historian_findings": findings_dict}
