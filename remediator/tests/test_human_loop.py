import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from remediator.human_loop import prompt_human, input_with_timeout

def test_input_with_timeout_non_tty():
    # If stdin is not a TTY, it should bypass and return 'n' immediately
    with patch("sys.stdin.isatty", return_value=False):
        ans = input_with_timeout("test prompt: ")
        assert ans == "n"

def test_input_with_timeout_windows_success():
    # Mock Windows msvcrt path
    mock_msvcrt = MagicMock()
    mock_msvcrt.kbhit.side_effect = [False, True, True]
    mock_msvcrt.getch.side_effect = [b"y", b"\r"]
    
    with patch("sys.stdin.isatty", return_value=True), \
         patch.dict("sys.modules", {"msvcrt": mock_msvcrt}), \
         patch("sys.stdout.write") as mock_write:
        ans = input_with_timeout("test prompt: ", timeout=5)
        assert ans == "y"

def test_input_with_timeout_windows_backspace():
    # Test typing a key, backspace, then enter
    mock_msvcrt = MagicMock()
    mock_msvcrt.kbhit.side_effect = [True, True, True]
    mock_msvcrt.getch.side_effect = [b"a", b"\b", b"\r"]
    
    with patch("sys.stdin.isatty", return_value=True), \
         patch.dict("sys.modules", {"msvcrt": mock_msvcrt}), \
         patch("sys.stdout.write"):
        ans = input_with_timeout("test prompt: ", timeout=5)
        assert ans == ""

def test_input_with_timeout_windows_timeout():
    mock_msvcrt = MagicMock()
    mock_msvcrt.kbhit.return_value = False
    
    with patch("sys.stdin.isatty", return_value=True), \
         patch.dict("sys.modules", {"msvcrt": mock_msvcrt}), \
         patch("sys.stdout.write"), \
         patch("time.time", side_effect=[0, 10]):
        ans = input_with_timeout("test prompt: ", timeout=5)
        assert ans == "n"

def test_input_with_timeout_unix_success():
    # Unix fallback mock path (ImportError on msvcrt)
    mock_select = MagicMock()
    mock_select.select.return_value = ([sys.stdin], [], [])
    
    with patch("sys.stdin.isatty", return_value=True), \
         patch.dict("sys.modules", {"msvcrt": None}), \
         patch("select.select", mock_select.select), \
         patch("sys.stdin.readline", return_value="y\n"), \
         patch("sys.stdout.write"):
        ans = input_with_timeout("test prompt: ", timeout=5)
        assert ans == "y"

def test_input_with_timeout_unix_timeout():
    mock_select = MagicMock()
    mock_select.select.return_value = ([], [], [])
    
    with patch("sys.stdin.isatty", return_value=True), \
         patch.dict("sys.modules", {"msvcrt": None}), \
         patch("select.select", mock_select.select), \
         patch("sys.stdout.write"):
        ans = input_with_timeout("test prompt: ", timeout=5)
        assert ans == "n"

def test_prompt_human_test_override():
    # Test setting REMEDIATOR_TEST_APPROVAL env var
    with patch.dict(os.environ, {"REMEDIATOR_TEST_APPROVAL": "true"}):
        res = prompt_human({"incident_id": "123"}, "restart")
        assert res is True

    with patch.dict(os.environ, {"REMEDIATOR_TEST_APPROVAL": "false"}):
        res = prompt_human({"incident_id": "123"}, "restart")
        assert res is False

def test_prompt_human_risk_categories():
    # Mock input_with_timeout to return 'y'
    with patch("remediator.human_loop.input_with_timeout", return_value="y"), \
         patch.dict(os.environ, {}):
        os.environ["REMEDIATOR_TEST_APPROVAL"] = "dummy"
        if "REMEDIATOR_TEST_APPROVAL" in os.environ:
            del os.environ["REMEDIATOR_TEST_APPROVAL"]
            
        # 1. High Risk Rollback
        res = prompt_human(
            {"incident_id": "123", "hypothesis": "OOM", "confidence": 0.8, "reasoning": "memory leak"}, 
            "rollback"
        )
        assert res is True

        # 2. Medium Risk Restart
        res = prompt_human(
            {"incident_id": "123", "hypothesis": "Crash", "confidence": 0.7, "reasoning": "cpu leak"}, 
            "restart"
        )
        assert res is True

        # 3. Low Risk Github PR
        res = prompt_human(
            {"incident_id": "123", "hypothesis": "Fix", "confidence": 0.9, "reasoning": "pr config"}, 
            "open_github_pr"
        )
        assert res is True

        # 4. Unknown/None Risk
        res = prompt_human(
            {"incident_id": "123", "hypothesis": "Fix", "confidence": 0.9, "reasoning": "pr config"}, 
            "none"
        )
        assert res is True

def test_input_with_timeout_windows_unicode_decode_error():
    # Test typing an invalid key byte (which fails UTF-8 decoding) and then enter
    mock_msvcrt = MagicMock()
    mock_msvcrt.kbhit.side_effect = [True, True, True]
    mock_msvcrt.getch.side_effect = [b"\xff", b"a", b"\r"]
    
    with patch("sys.stdin.isatty", return_value=True), \
         patch.dict("sys.modules", {"msvcrt": mock_msvcrt}), \
         patch("sys.stdout.write"):
        ans = input_with_timeout("test prompt: ", timeout=5)
        assert ans == "a"

def test_prompt_human_non_dict_hypothesis():
    # Hypothesis is an object with attributes (like a Pydantic model)
    class MockHypothesis:
        incident_id = "inc-non-dict"
        hypothesis = "OOM on frontend"
        confidence = 0.92
        reasoning = "Memory usage exceeds limit"

    with patch("remediator.human_loop.input_with_timeout", return_value="y"), \
         patch.dict(os.environ):
        os.environ.pop("REMEDIATOR_TEST_APPROVAL", None)
        res = prompt_human(MockHypothesis(), "restart")
        assert res is True

def test_prompt_human_rejection():
    # Test operator input is 'n' (remdiation action rejected)
    with patch("remediator.human_loop.input_with_timeout", return_value="n"), \
         patch.dict(os.environ):
        os.environ.pop("REMEDIATOR_TEST_APPROVAL", None)
        res = prompt_human(
            {"incident_id": "123", "hypothesis": "OOM", "confidence": 0.8, "reasoning": "memory leak"}, 
            "rollback"
        )
        assert res is False
