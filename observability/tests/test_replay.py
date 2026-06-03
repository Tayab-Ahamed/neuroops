from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner
from replay import fetch_traces, get_tag_value, main, process_spans, render_replay

# --- get_tag_value tests ---


def test_get_tag_value_exists():
    span = {
        "tags": [
            {"key": "agent.name", "value": "detective"},
            {"key": "agent.confidence", "value": 0.85},
        ]
    }
    assert get_tag_value(span, "agent.name") == "detective"
    assert get_tag_value(span, "agent.confidence") == 0.85


def test_get_tag_value_not_exists():
    span = {"tags": [{"key": "agent.name", "value": "detective"}]}
    assert get_tag_value(span, "agent.confidence") is None


def test_get_tag_value_empty_or_no_tags():
    assert get_tag_value({}, "agent.name") is None
    assert get_tag_value({"tags": []}, "agent.name") is None


# --- fetch_traces tests ---


@patch("httpx.get")
def test_fetch_traces_success(mock_get):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"data": []}
    mock_get.return_value = mock_response

    result = fetch_traces("http://localhost:16686", "inc-123")
    assert result == {"data": []}
    mock_get.assert_called_once_with(
        "http://localhost:16686/api/traces",
        params={"service": "neuroops.agent", "tag": "incident.id:inc-123"},
        timeout=10.0,
    )


@patch("httpx.get")
def test_fetch_traces_http_error(mock_get):
    mock_get.side_effect = httpx.RequestError("Connection failed", request=MagicMock())

    with pytest.raises(SystemExit) as exc_info:
        fetch_traces("http://localhost:16686", "inc-123")

    assert exc_info.value.code == 1


# --- process_spans tests ---


def test_process_spans_empty():
    assert process_spans({}) == []
    assert process_spans({"data": []}) == []


def test_process_spans_sorted():
    data = {
        "data": [
            {
                "spans": [
                    {"spanID": "span2", "startTime": 2000},
                    {"spanID": "span1", "startTime": 1000},
                ]
            }
        ]
    }
    spans = process_spans(data)
    assert len(spans) == 2
    assert spans[0]["spanID"] == "span1"
    assert spans[1]["spanID"] == "span2"


# --- render_replay tests ---


def test_render_replay_empty(capsys):
    render_replay([], "inc-123")
    captured = capsys.readouterr()
    assert (
        "No agent reasoning traces found" in captured.out
        or "No agent reasoning traces found" in captured.err
    )


def test_render_replay_no_agent_name(capsys):
    spans = [{"spanID": "span1", "startTime": 1000000}]  # No agent.name tag
    render_replay(spans, "inc-123")
    captured = capsys.readouterr()
    assert "Incident Summary Incomplete" in captured.out


def test_render_replay_with_spans_and_supervisor_true(capsys):
    spans = [
        {
            "spanID": "span1",
            "startTime": 1680000000000000,
            "tags": [
                {"key": "agent.name", "value": "detective"},
                {"key": "agent.decision", "value": "High CPU utilization on backend service"},
                {"key": "agent.confidence", "value": 0.85},
                {"key": "agent.tool_called", "value": "compare_services"},
                {"key": "agent.latency_ms", "value": 450},
                {"key": "agent.tokens_used", "value": 1200},
            ],
        },
        {
            "spanID": "span2",
            "startTime": 1680000002000000,
            "tags": [
                {"key": "agent.name", "value": "supervisor_synthesize"},
                {"key": "agent.decision", "value": "Rolled back faulty commit"},
                {"key": "agent.confidence", "value": 0.95},
                {"key": "agent.recommended_action", "value": "rollback"},
                {"key": "agent.requires_human_approval", "value": True},
                {"key": "agent.latency_ms", "value": 600},
                {"key": "agent.tokens_used", "value": 1500},
            ],
        },
    ]
    render_replay(spans, "inc-123")
    captured = capsys.readouterr()
    assert "Multi-Agent Root Cause Analysis" in captured.out
    assert "detective" in captured.out
    assert "supervisor_synthesize" in captured.out
    assert "ROLLBACK" in captured.out
    assert "YES" in captured.out


def test_render_replay_with_spans_and_supervisor_false(capsys):
    spans = [
        {
            "spanID": "span1",
            "startTime": 1680000000000000,
            "tags": [
                {"key": "agent.name", "value": "detective"},
                {"key": "agent.decision", "value": "Unhealthy state"},
                {"key": "agent.confidence", "value": 0.70},
                {"key": "agent.tool_called", "value": "compare_services"},
            ],
        },
        {
            "spanID": "span2",
            "startTime": 1680000002000000,
            "tags": [
                {"key": "agent.name", "value": "supervisor_synthesize"},
                {"key": "agent.decision", "value": "Restart backend pod"},
                {"key": "agent.confidence", "value": 0.55},
                {"key": "agent.recommended_action", "value": "none"},
                {"key": "agent.requires_human_approval", "value": False},
            ],
        },
    ]
    render_replay(spans, "inc-123")
    captured = capsys.readouterr()
    assert "NONE" in captured.out
    assert "NO" in captured.out


def test_render_replay_invalid_confidence_and_long_decision(capsys):
    spans = [
        {
            "spanID": "span1",
            "startTime": 1680000000000000,
            "tags": [
                {"key": "agent.name", "value": "detective"},
                {"key": "agent.decision", "value": "A" * 100},  # Extremely long decision
                {"key": "agent.confidence", "value": "invalid_conf"},  # Invalid confidence type
            ],
        }
    ]
    render_replay(spans, "inc-123")
    captured = capsys.readouterr()
    assert "A" * 50 in captured.out
    assert "invalid_conf" in captured.out


# --- CLI integration main tests ---


@patch("replay.fetch_traces")
def test_main_cli(mock_fetch):
    mock_fetch.return_value = {
        "data": [
            {
                "spans": [
                    {
                        "spanID": "span1",
                        "startTime": 1680000000000000,
                        "tags": [
                            {"key": "agent.name", "value": "detective"},
                            {"key": "agent.decision", "value": "Healthy"},
                            {"key": "agent.confidence", "value": 0.99},
                        ],
                    }
                ]
            }
        ]
    }

    runner = CliRunner()
    result = runner.invoke(main, ["--incident-id", "inc-123"])

    assert result.exit_code == 0
    assert "Connecting to Jaeger" in result.output
    assert "detective" in result.output
