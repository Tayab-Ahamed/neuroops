import os
import tempfile
from unittest.mock import patch

import pytest
from agents.llm import get_llm, get_llm_model_name
from agents.supervisor import compute_complexity
from incident_store import IncidentStore
from state import AgentState, Alert


def test_compute_complexity():
    # Base state with minimal settings
    alert_p3 = Alert(
        id="alert-p3",
        service="backend",
        severity="P3",
        timestamp=1716390000.0,
        metric_snapshot={},
        anomaly_score=0.0,
    )
    state: AgentState = {
        "incident_id": "inc-1",
        "alert": alert_p3,
        "detective_findings": None,
        "topologist_findings": None,
        "historian_findings": None,
        "log_findings": None,
        "hypothesis": None,
        "confidence": None,
        "recommended_action": None,
        "requires_human_approval": False,
        "reasoning": None,
        "tokens_used": 0,
        "execute_remediation": False,
        "remediation_result": None,
        "similar_incidents": [],
        "complexity_score": 0.5,
    }

    # Scenario 1: P3 alert, 0 anomaly score, no correlated services -> complexity 0.0
    assert compute_complexity(state) == 0.0

    # Scenario 2: P1 severity (+0.1)
    alert_p1 = Alert(
        id="alert-p1",
        service="backend",
        severity="P1",
        timestamp=1716390000.0,
        metric_snapshot={},
        anomaly_score=0.0,
    )
    state["alert"] = alert_p1
    assert pytest.approx(compute_complexity(state), 0.01) == 0.1

    # Scenario 3: P2 severity (+0.3)
    alert_p2 = Alert(
        id="alert-p2",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={},
        anomaly_score=0.0,
    )
    state["alert"] = alert_p2
    assert pytest.approx(compute_complexity(state), 0.01) == 0.3

    # Scenario 4: Anomaly score contribution (+ min(abs(score)*0.4, 0.4))
    # anomaly_score = 0.5 -> +0.2 complexity
    alert_p2_anom = Alert(
        id="alert-p2-anom",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={},
        anomaly_score=0.5,
    )
    state["alert"] = alert_p2_anom
    assert pytest.approx(compute_complexity(state), 0.01) == 0.5  # 0.3 (P2) + 0.2 (anomaly)

    # Scenario 5: High anomaly score caps at +0.4
    alert_p2_high_anom = Alert(
        id="alert-p2-high-anom",
        service="backend",
        severity="P2",
        timestamp=1716390000.0,
        metric_snapshot={},
        anomaly_score=2.0,
    )
    state["alert"] = alert_p2_high_anom
    assert pytest.approx(compute_complexity(state), 0.01) == 0.7  # 0.3 (P2) + 0.4 (cap)

    # Scenario 6: Correlated services (+0.2 per service, max 3 -> +0.6 max)
    state["detective_findings"] = {"correlated_services": ["svc1", "svc2"]}
    assert pytest.approx(compute_complexity(state), 0.01) == 1.0  # 0.7 + 0.4 = 1.1 -> capped at 1.0

    state["detective_findings"] = {"correlated_services": ["svc1"]}
    assert pytest.approx(compute_complexity(state), 0.01) == 0.9  # 0.7 + 0.2 = 0.9


def test_get_llm_model_name_helper(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("MODEL_ROUTING_ENABLED", "true")

    # Haiku boundary (< 0.35)
    assert get_llm_model_name(0.3) == "claude-haiku-4-5-20251001"
    # Sonnet boundary (0.35 - 0.70)
    assert get_llm_model_name(0.5) == "claude-sonnet-4-6"
    assert get_llm_model_name(0.7) == "claude-sonnet-4-6"
    assert get_llm_model_name(0.8) == "claude-sonnet-4-6"

    # With routing disabled
    monkeypatch.setenv("MODEL_ROUTING_ENABLED", "false")
    monkeypatch.setenv("ANTHROPIC_MODEL", "custom-anthropic-model")
    assert get_llm_model_name(0.3) == "custom-anthropic-model"


@patch("langchain_anthropic.ChatAnthropic")
def test_get_llm_routing(mock_chat_anthropic, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("MODEL_ROUTING_ENABLED", "true")

    # complexity < 0.35 -> claude-haiku-4-5-20251001
    mock_chat_anthropic.reset_mock()
    get_llm(complexity_score=0.2)
    mock_chat_anthropic.assert_called_once()
    assert mock_chat_anthropic.call_args[1]["model"] == "claude-haiku-4-5-20251001"
    assert "max_tokens" not in mock_chat_anthropic.call_args[1]

    # complexity 0.35 <= x <= 0.7 -> claude-sonnet-4-6
    mock_chat_anthropic.reset_mock()
    get_llm(complexity_score=0.5)
    mock_chat_anthropic.assert_called_once()
    assert mock_chat_anthropic.call_args[1]["model"] == "claude-sonnet-4-6"
    assert "max_tokens" not in mock_chat_anthropic.call_args[1]

    # complexity > 0.7 -> claude-sonnet-4-6 with max_tokens=4096
    mock_chat_anthropic.reset_mock()
    get_llm(complexity_score=0.8)
    mock_chat_anthropic.assert_called_once()
    assert mock_chat_anthropic.call_args[1]["model"] == "claude-sonnet-4-6"
    assert mock_chat_anthropic.call_args[1]["max_tokens"] == 4096


def test_db_persistence_and_cost_aggregation():
    # Use a temporary database for testing
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_temp_path = f.name

    try:
        store = IncidentStore(db_path=db_temp_path)

        # Confirm the model_used column is migrated
        with store._connect() as conn:
            columns = [
                row["name"] for row in conn.execute("PRAGMA table_info(incidents)").fetchall()
            ]
            assert "model_used" in columns

        # Save an incident with Haiku
        store.save_incident(
            incident_id="inc-haiku",
            service="backend",
            alert_id="alert-h",
            hypothesis="Haiku diag",
            confidence=0.9,
            recommended_action="restart",
            requires_human_approval=False,
            reasoning="Simple",
            tokens_used=1000,
            remediation_result=None,
            trace_timeline=[],
            model_used="claude-haiku-4-5-20251001",
        )

        # Save an incident with Sonnet
        store.save_incident(
            incident_id="inc-sonnet",
            service="frontend",
            alert_id="alert-s",
            hypothesis="Sonnet diag",
            confidence=0.8,
            recommended_action="rollback",
            requires_human_approval=True,
            reasoning="Complex",
            tokens_used=5000,
            remediation_result=None,
            trace_timeline=[],
            model_used="claude-sonnet-4-6",
        )

        # Save an incident with None model (should default to Sonnet in calculations)
        store.save_incident(
            incident_id="inc-default",
            service="database",
            alert_id="alert-d",
            hypothesis="Default diag",
            confidence=0.75,
            recommended_action="none",
            requires_human_approval=True,
            reasoning="Undefined",
            tokens_used=2000,
            remediation_result=None,
            trace_timeline=[],
            model_used=None,
        )

        # Test list_incidents returns model_used
        incidents = store.list_incidents()
        incidents_by_id = {inc["incident_id"]: inc for inc in incidents}
        assert incidents_by_id["inc-haiku"]["model_used"] == "claude-haiku-4-5-20251001"
        assert incidents_by_id["inc-sonnet"]["model_used"] == "claude-sonnet-4-6"
        assert incidents_by_id["inc-default"]["model_used"] is None

        # Test get_detailed_cost_stats
        stats = store.get_detailed_cost_stats()

        assert stats["total_tokens"] == 8000  # 1000 + 5000 + 2000

        haiku_breakdown = stats["model_breakdown"]["haiku"]
        sonnet_breakdown = stats["model_breakdown"]["sonnet"]

        assert haiku_breakdown["calls"] == 1
        assert haiku_breakdown["tokens"] == 1000
        # Haiku cost: (800 input * 0.00025 / 1000) + (200 output * 0.00125 / 1000)
        # = 0.0002 + 0.00025 = 0.00045
        assert pytest.approx(haiku_breakdown["cost_usd"], 0.000001) == 0.00045

        # Sonnet + default: 5000 + 2000 = 7000 tokens
        assert sonnet_breakdown["calls"] == 2
        assert sonnet_breakdown["tokens"] == 7000
        # Sonnet cost: (5600 input * 0.003 / 1000) + (1400 output * 0.015 / 1000)
        # = 0.0168 + 0.021 = 0.0378
        assert pytest.approx(sonnet_breakdown["cost_usd"], 0.000001) == 0.0378

        # Total cost = 0.00045 + 0.0378 = 0.03825
        assert pytest.approx(stats["total_cost_usd"], 0.000001) == 0.03825

        # Cost if all were Sonnet: 8000 tokens * (80% * 0.003 / 1000 + 20% * 0.015 / 1000)
        # = 8000 * (0.0024 + 0.003) / 1000 = 8000 * 0.0054 / 1000 = 0.0432
        # Savings = 0.0432 - 0.03825 = 0.00495
        assert pytest.approx(stats["estimated_savings_vs_sonnet_only_usd"], 0.000001) == 0.00495

    finally:
        try:
            os.remove(db_temp_path)
        except OSError:
            pass
