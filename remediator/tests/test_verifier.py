import os
from unittest.mock import MagicMock, patch

from remediator.verifier import verify_resolution


def test_verify_resolution_no_alert_id():
    # Lack of alert ID should return True instantly
    assert verify_resolution(None) is True
    assert verify_resolution({}) is True
    assert verify_resolution(MagicMock(id=None)) is True


def test_verify_resolution_test_approval():
    # Test environment override should return True instantly
    with patch.dict(os.environ, {"REMEDIATOR_TEST_APPROVAL": "true"}):
        assert verify_resolution({"id": "alert-123"}) is True


def test_verify_resolution_success():
    # Mock successful resolution where alert ID disappears from detector active alerts
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"id": "alert-456"}]  # alert-123 is cleared

    mock_client = MagicMock()
    mock_client.__enter__.return_value.get.return_value = mock_response

    with patch("httpx.Client", return_value=mock_client), patch.dict(os.environ):
        os.environ.pop("REMEDIATOR_TEST_APPROVAL", None)
        assert (
            verify_resolution({"id": "alert-123", "service": "backend"}, timeout_seconds=10) is True
        )


def test_verify_resolution_timeout():
    # Mock where alert-123 remains active, causing a timeout
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"id": "alert-123"}]  # alert-123 remains active

    mock_client = MagicMock()
    mock_client.__enter__.return_value.get.return_value = mock_response

    with (
        patch("httpx.Client", return_value=mock_client),
        patch("time.sleep"),
        patch("time.time", side_effect=[0, 5, 10, 15, 200]),
        patch.dict(os.environ),
    ):
        os.environ.pop("REMEDIATOR_TEST_APPROVAL", None)
        assert (
            verify_resolution({"id": "alert-123", "service": "backend"}, timeout_seconds=10)
            is False
        )


def test_verify_resolution_non_200_and_error():
    # Mock non-200 status code followed by an exception to test error resilience
    mock_response_bad = MagicMock()
    mock_response_bad.status_code = 500

    mock_client = MagicMock()
    # First request returns 500, second throws connection error, third succeeds with empty active alerts (cleared!)
    mock_response_ok = MagicMock()
    mock_response_ok.status_code = 200
    mock_response_ok.json.return_value = []

    mock_client.__enter__.return_value.get.side_effect = [
        mock_response_bad,
        Exception("connection timeout"),
        mock_response_ok,
    ]

    with (
        patch("httpx.Client", return_value=mock_client),
        patch("time.sleep"),
        patch.dict(os.environ),
    ):
        os.environ.pop("REMEDIATOR_TEST_APPROVAL", None)

        # Pydantic-like model input test
        mock_alert = MagicMock()
        mock_alert.id = "alert-123"
        mock_alert.service = "backend"

        assert verify_resolution(mock_alert, timeout_seconds=120) is True


def test_verify_resolution_non_dict_active_alerts():
    # Mock where active alerts list contains custom objects with `id` attribute instead of dicts
    class CustomAlert:
        def __init__(self, alert_id):
            self.id = alert_id

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [CustomAlert("alert-456")]

    mock_client = MagicMock()
    mock_client.__enter__.return_value.get.return_value = mock_response

    with patch("httpx.Client", return_value=mock_client), patch.dict(os.environ):
        os.environ.pop("REMEDIATOR_TEST_APPROVAL", None)
        assert (
            verify_resolution({"id": "alert-123", "service": "backend"}, timeout_seconds=10) is True
        )
