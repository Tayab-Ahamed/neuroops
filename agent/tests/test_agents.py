from unittest.mock import MagicMock, patch

import pytest
from agents.detective import DetectiveOutput, detective_node
from agents.historian import HistorianOutput, historian_node
from agents.supervisor import SupervisorOutput, supervisor_init_node, supervisor_synthesize_node
from agents.topologist import TopologistOutput, topologist_node
from state import AgentState, Alert


class MockStructuredLLM:
    def __init__(self, final_response):
        self.final_response = final_response

    async def ainvoke(self, messages, *args, **kwargs):
        return self.final_response


class MockLLM:
    def __init__(self, tool_call_response=None, final_response=None):
        self.tool_call_response = tool_call_response
        self.final_response = final_response

    def bind_tools(self, tools):
        return self

    def with_structured_output(self, output_schema):
        return MockStructuredLLM(self.final_response)

    async def ainvoke(self, messages, *args, **kwargs):
        from langchain_core.messages import ToolMessage

        has_tool_msg = any(isinstance(m, ToolMessage) for m in messages)

        if self.tool_call_response and not has_tool_msg:
            return self.tool_call_response

        mock_no_tc = MagicMock()
        mock_no_tc.tool_calls = []
        return mock_no_tc


@pytest.mark.asyncio
@patch("langchain_anthropic.ChatAnthropic")
async def test_detective_node_llm_path(mock_chat_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    # 1. Mock tool call response
    mock_tc_res = MagicMock()
    mock_tc_res.tool_calls = [
        {
            "name": "compare_services",
            "args": {"metric": "latency", "time_window": "5m"},
            "id": "call_123",
        }
    ]

    # 2. Mock final structured response
    final_output = DetectiveOutput(
        correlated_services=["backend"],
        likely_origin="backend",
        evidence="Prometheus shows backend has high CPU",
    )

    mock_llm = MockLLM(tool_call_response=mock_tc_res, final_response=final_output)
    mock_chat_anthropic.return_value = mock_llm

    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8},
        anomaly_score=-0.45,
    )

    state = {"alert": alert, "incident_id": "inc-123"}
    res = await detective_node(state)

    assert res["detective_findings"]["likely_origin"] == "backend"
    assert "backend" in res["detective_findings"]["correlated_services"]


@pytest.mark.asyncio
@patch("langchain_anthropic.ChatAnthropic")
async def test_topologist_node_llm_path(mock_chat_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_tc_res = MagicMock()
    mock_tc_res.tool_calls = [
        {"name": "get_service_dependencies", "args": {"service_name": "backend"}, "id": "call_456"}
    ]

    final_output = TopologistOutput(
        upstream_services=["frontend"], downstream_services=["database"], bottleneck="backend"
    )

    mock_llm = MockLLM(tool_call_response=mock_tc_res, final_response=final_output)
    mock_chat_anthropic.return_value = mock_llm

    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8},
        anomaly_score=-0.45,
    )

    state = {"alert": alert, "incident_id": "inc-123"}
    res = await topologist_node(state)

    assert res["topologist_findings"]["bottleneck"] == "backend"


@pytest.mark.asyncio
@patch("langchain_anthropic.ChatAnthropic")
async def test_historian_node_llm_path(mock_chat_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_tc_res = MagicMock()
    mock_tc_res.tool_calls = [
        {"name": "get_recent_deploys", "args": {"repo": "neuroops/app"}, "id": "call_789"}
    ]

    final_output = HistorianOutput(
        recent_deploys=[{"commit": "a1b2"}], suspect_commit="a1b2", deploy_time="2026-05-22"
    )

    mock_llm = MockLLM(tool_call_response=mock_tc_res, final_response=final_output)
    mock_chat_anthropic.return_value = mock_llm

    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8},
        anomaly_score=-0.45,
    )

    state = {"alert": alert, "incident_id": "inc-123"}
    res = await historian_node(state)

    assert res["historian_findings"]["suspect_commit"] == "a1b2"


@pytest.mark.asyncio
@patch("langchain_openai.ChatOpenAI")
async def test_supervisor_synthesize_node_openai_path(mock_chat_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    final_output = SupervisorOutput(
        hypothesis="Memory leak in backend service",
        confidence=0.95,
        recommended_action="restart",
        requires_human_approval=False,
        reasoning="Historian saw config update, Detective saw high CPU",
    )

    mock_llm = MockLLM(final_response=final_output)
    mock_chat_openai.return_value = mock_llm

    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8},
        anomaly_score=-0.45,
    )

    state: AgentState = {
        "alert": alert,
        "incident_id": "inc-123",
        "detective_findings": {"likely_origin": "backend"},
        "topologist_findings": {"bottleneck": "backend"},
        "historian_findings": {"suspect_commit": "a1b2"},
        "hypothesis": None,
        "confidence": None,
        "recommended_action": None,
        "requires_human_approval": False,
    }

    res = await supervisor_synthesize_node(state)
    assert res["hypothesis"] == "Memory leak in backend service"
    assert res["confidence"] == 0.95
    assert res["recommended_action"] == "restart"


@pytest.mark.asyncio
async def test_supervisor_init_node():
    state_preset = {"incident_id": "inc-preset"}
    res_preset = await supervisor_init_node(state_preset)
    assert res_preset["incident_id"] == "inc-preset"

    state_empty = {"incident_id": ""}
    res_empty = await supervisor_init_node(state_empty)
    assert res_empty["incident_id"].startswith("inc-")


@pytest.mark.asyncio
@patch("langchain_openai.ChatOpenAI")
async def test_detective_node_openai_path(mock_chat_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    mock_tc_res = MagicMock()
    mock_tc_res.tool_calls = []

    final_output = DetectiveOutput(
        correlated_services=["backend"],
        likely_origin="backend",
        evidence="Prometheus shows backend has high CPU via GPT-4o",
    )

    mock_llm = MockLLM(tool_call_response=mock_tc_res, final_response=final_output)
    mock_chat_openai.return_value = mock_llm

    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8},
        anomaly_score=-0.45,
    )

    state = {"alert": alert, "incident_id": "inc-123"}
    res = await detective_node(state)
    assert res["detective_findings"]["likely_origin"] == "backend"


@pytest.mark.asyncio
@patch("langchain_openai.ChatOpenAI")
async def test_topologist_node_openai_path(mock_chat_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    mock_tc_res = MagicMock()
    mock_tc_res.tool_calls = []

    final_output = TopologistOutput(
        upstream_services=["frontend"], downstream_services=["database"], bottleneck="backend"
    )

    mock_llm = MockLLM(tool_call_response=mock_tc_res, final_response=final_output)
    mock_chat_openai.return_value = mock_llm

    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8},
        anomaly_score=-0.45,
    )

    state = {"alert": alert, "incident_id": "inc-123"}
    res = await topologist_node(state)
    assert res["topologist_findings"]["bottleneck"] == "backend"


@pytest.mark.asyncio
@patch("langchain_openai.ChatOpenAI")
async def test_historian_node_openai_path(mock_chat_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    mock_tc_res = MagicMock()
    mock_tc_res.tool_calls = []

    final_output = HistorianOutput(
        recent_deploys=[{"commit": "a1b2"}], suspect_commit="a1b2", deploy_time="2026-05-22"
    )

    mock_llm = MockLLM(tool_call_response=mock_tc_res, final_response=final_output)
    mock_chat_openai.return_value = mock_llm

    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8},
        anomaly_score=-0.45,
    )

    state = {"alert": alert, "incident_id": "inc-123"}
    res = await historian_node(state)
    assert res["historian_findings"]["suspect_commit"] == "a1b2"


@pytest.mark.asyncio
@patch("langchain_anthropic.ChatAnthropic")
async def test_supervisor_synthesize_node_anthropic_path(mock_chat_anthropic, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    final_output = SupervisorOutput(
        hypothesis="Memory leak in backend service",
        confidence=0.95,
        recommended_action="restart",
        requires_human_approval=False,
        reasoning="Historian saw config update, Detective saw high CPU",
    )

    mock_llm = MockLLM(final_response=final_output)
    mock_chat_anthropic.return_value = mock_llm

    alert = Alert(
        id="alert-111",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={"cpu": 0.8},
        anomaly_score=-0.45,
    )

    state: AgentState = {
        "alert": alert,
        "incident_id": "inc-123",
        "detective_findings": {"likely_origin": "backend"},
        "topologist_findings": {"bottleneck": "backend"},
        "historian_findings": {"suspect_commit": "a1b2"},
        "hypothesis": None,
        "confidence": None,
        "recommended_action": None,
        "requires_human_approval": False,
    }

    res = await supervisor_synthesize_node(state)
    assert res["hypothesis"] == "Memory leak in backend service"
