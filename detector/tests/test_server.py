import asyncio
import importlib
import os
import sys

# Add parent directory to path so imports work cleanly in test suite
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set environment variables for testing
os.environ["MODEL_PATH"] = "checkpoints/test_isolation_forest.joblib"

with patch("scraper.PrometheusConnect") as mock_prom:
    import server
    from server import active_alerts, app

client = TestClient(app)


def test_health_endpoint():
    # Test health endpoint when model is not loaded
    server.model_loaded = False
    active_alerts.clear()

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["model_loaded"] is False
    assert data["active_alerts_count"] == 0

    # Test health endpoint when model is loaded
    server.model_loaded = True
    active_alerts.append(MagicMock())
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["model_loaded"] is True
    assert data["active_alerts_count"] == 1


def test_alerts_endpoint():
    active_alerts.clear()
    response = client.get("/alerts")
    assert response.status_code == 200
    assert response.json() == []


@patch("server.collect_historical_baseline")
def test_train_endpoint(mock_collect):
    # Mock return value of collect_historical_baseline
    mock_collect.return_value = [MagicMock()]

    # We will trigger baseline training
    response = client.post("/baseline/train?minutes=10")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "training_started"
    assert "10m" in data["message"]


def test_startup_model_load_exception():
    # Test startup model loading failure path
    with (
        patch("os.path.exists", return_value=True),
        patch(
            "models.isolation_forest.IsolationForestModel.load",
            side_effect=Exception("Failed to load"),
        ),
        patch("scraper.PrometheusConnect"),
    ):
        # Reload server to trigger global startup exception handler
        importlib.reload(server)
        assert server.model_loaded is False


def test_startup_no_model_checkpoint():
    # Test startup model loading path when no checkpoint exists
    with patch("os.path.exists", return_value=False), patch("scraper.PrometheusConnect"):
        importlib.reload(server)
        assert server.model_loaded is False


def test_lifespan_startup_shutdown():
    # Test that lifespan startup/shutdown context manager executes without errors
    # We patch background_scraping_loop to block so it triggers CancelledError on cancel
    async def mock_loop():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    with (
        patch("server.background_scraping_loop", side_effect=mock_loop),
        patch("scraper.PrometheusConnect"),
    ):
        with TestClient(app) as test_client:
            response = test_client.get("/health")
            assert response.status_code == 200


@pytest.mark.asyncio
async def test_background_scraping_loop_success():
    # Mock scrape_metrics and model predictions
    mock_window = MagicMock()
    mock_window.service_name = "frontend"
    mock_window.feature_vector = {"error_rate": 0.0}

    server.scraper.scrape_metrics = MagicMock(return_value=[mock_window])
    server.model.score = MagicMock(return_value=-0.1)
    server.model.predict = MagicMock(return_value=False)
    server.alerter.process_window = MagicMock(return_value=None)

    server.model_loaded = True

    # Mock asyncio.sleep to raise CancelledError on first call to break the loop
    with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
        try:
            await server.background_scraping_loop()
        except asyncio.CancelledError:
            pass

    server.scraper.scrape_metrics.assert_called_once()
    server.model.score.assert_called_once_with(mock_window)


@pytest.mark.asyncio
async def test_background_scraping_loop_alert_limit():
    # Mock scrape_metrics and model predictions to trigger alert
    mock_window = MagicMock()
    mock_window.service_name = "frontend"
    mock_window.feature_vector = {"error_rate": 0.0}

    server.scraper.scrape_metrics = MagicMock(return_value=[mock_window])
    server.model.score = MagicMock(return_value=-0.8)  # High score for anomaly
    server.model.predict = MagicMock(return_value=True)  # Is anomaly

    # Mock alerter.process_window to return a mock Alert object
    mock_alert = MagicMock()
    server.alerter.process_window = MagicMock(return_value=mock_alert)

    server.model_loaded = True

    # Fill active_alerts with 500 mock alerts to trigger line 67 size limiter
    server.active_alerts.clear()
    for _i in range(500):
        server.active_alerts.append(MagicMock())

    with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
        try:
            await server.background_scraping_loop()
        except asyncio.CancelledError:
            pass

    # Assert that the active_alerts list size is kept at 500
    assert len(server.active_alerts) == 500


@pytest.mark.asyncio
async def test_background_scraping_loop_warmup():
    mock_window = MagicMock()
    mock_window.service_name = "frontend"
    server.scraper.scrape_metrics = MagicMock(return_value=[mock_window])

    server.model_loaded = False  # Warmup Mode

    with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
        try:
            await server.background_scraping_loop()
        except asyncio.CancelledError:
            pass

    server.scraper.scrape_metrics.assert_called_once()


@pytest.mark.asyncio
async def test_background_scraping_loop_exception():
    server.scraper.scrape_metrics = MagicMock(side_effect=Exception("Prometheus down"))

    with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
        try:
            await server.background_scraping_loop()
        except asyncio.CancelledError:
            pass

    server.scraper.scrape_metrics.assert_called_once()


@patch("server.collect_historical_baseline")
def test_async_training_empty_baseline(mock_collect):
    mock_collect.return_value = []  # Empty list aborts training
    server.model_loaded = False

    server.run_async_training(10)

    assert server.model_loaded is False


@patch("server.collect_historical_baseline")
def test_async_training_exception(mock_collect):
    mock_collect.side_effect = Exception("Prometheus error")
    server.model_loaded = False

    server.run_async_training(10)

    assert server.model_loaded is False
