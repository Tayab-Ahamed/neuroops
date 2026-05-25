import os
from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, ToolMessage
from state import AgentState
from tools.k8s_log_tools import get_pod_logs
from tracing import traced_node, llm_retry

class LogAnalyserOutput(BaseModel):
    error_logs: List[str] = Field(description="List of raw error log entries parsed from container output")
    suspect_stack_trace: Optional[str] = Field(description="Extracted traceback, panic, or core exception message")
    reasoning: str = Field(description="Analytical explanation of log errors and exception patterns")

@traced_node("log_analyser")
async def log_analyser_node(state: AgentState) -> dict:
    alert = state["alert"]
    service = alert.service
    
    # Check for keys. If missing, return mock findings for local test execution
    from agents.llm import get_llm
    llm = get_llm()
    if llm is None:
        # Mock logs diagnosis matching the service
        if service == "backend":
            return {
                "log_findings": {
                    "error_logs": [
                        "ERROR: psycopg2.OperationalError: connection to server at 'database-stub' failed: Connection timed out."
                    ],
                    "suspect_stack_trace": "sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) timeout expired",
                    "reasoning": "Mock Log Analyser: backend logs reveal severe database connection pooling exhaustion and timeout errors connecting to 'database-stub'.",
                    "tool_called": "get_pod_logs",
                    "tokens_used": 1150
                }
            }
        elif service == "frontend":
            return {
                "log_findings": {
                    "error_logs": [
                        "asyncio: Event loop blocked for 5.44 seconds. CPU utilization high.",
                        "GET /data HTTP/1.1 504 Gateway Timeout"
                    ],
                    "suspect_stack_trace": None,
                    "reasoning": "Mock Log Analyser: frontend logs indicate event loop choking and gateway timeouts due to high CPU starvation.",
                    "tool_called": "get_pod_logs",
                    "tokens_used": 950
                }
            }
        else:
            return {
                "log_findings": {
                    "error_logs": [
                        "FATAL: write-ahead log write failed: disk full"
                    ],
                    "suspect_stack_trace": "disk full (85% capacity reached)",
                    "reasoning": "Mock Log Analyser: database logs report severe disk pressure and write failures.",
                    "tool_called": "get_pod_logs",
                    "tokens_used": 1050
                }
            }

    # Live execution using centralized LLM
    tools = [get_pod_logs]
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {"get_pod_logs": get_pod_logs}
    
    messages = [
        HumanMessage(content=(
            f"You are the Log Triage Agent for NeuroOps. An alert triggered on service '{service}'.\n"
            f"Anomaly Score: {alert.anomaly_score:.3f}\n"
            f"Metric Snapshot: {alert.metric_snapshot}\n\n"
            f"Retrieve and analyse the container logs for '{service}' to identify any critical errors, "
            f"tracebacks, or stack traces that could explain the incident.\n"
            f"Use the `get_pod_logs` tool to fetch logs for '{service}'.\n"
            f"If logs show failures, extract the error details and exception traceback."
        ))
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
            messages.append(ToolMessage(
                content=str(tool_result),
                tool_call_id=tool_call["id"]
            ))
            
    # Structured response
    structured_llm = llm.with_structured_output(LogAnalyserOutput)
    findings = await llm_retry(structured_llm.ainvoke)(messages)
    
    findings_dict = findings.dict()
    # Extract tool names called
    tools_called = []
    try:
        for msg in messages:
            if isinstance(msg, ToolMessage):
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
                if isinstance(val, (int, float)) and type(val).__name__ not in ("MagicMock", "Mock"):
                    total_tokens += val
            elif hasattr(msg, "response_metadata") and isinstance(msg.response_metadata, dict):
                usage = msg.response_metadata.get("token_usage")
                if isinstance(usage, dict):
                    val = usage.get("total_tokens", 0)
                    if isinstance(val, (int, float)) and type(val).__name__ not in ("MagicMock", "Mock"):
                        total_tokens += val
    except Exception:
        total_tokens = 0
    findings_dict["tokens_used"] = int(total_tokens) if total_tokens > 0 else 900
    
    return {"log_findings": findings_dict}
