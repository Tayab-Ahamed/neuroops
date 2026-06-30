import asyncio
import os
import threading
from contextlib import asynccontextmanager
from typing import Any

import httpx
import structlog
from alerter import Alert, Alerter
from auth import verify_api_key
from baseline_collector import collect_historical_baseline
from correlator import AlertCorrelator, CorrelatedAlert
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from models.forecaster import TrendForecaster
from models.isolation_forest import IsolationForestModel
from models.sequence_forecaster import SequenceForecastModel
from pydantic import BaseModel
from scraper import MetricWindow, PrometheusScraper
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Prometheus metrics instrumentation
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _prom_registry = CollectorRegistry()
    ALERTS_ACTIVE = Gauge(
        "neuroops_alerts_active_total",
        "Number of currently active alerts in the detector",
        registry=_prom_registry,
    )
    ANOMALY_SCORE = Histogram(
        "neuroops_anomaly_score",
        "Distribution of anomaly scores produced by IsolationForest",
        buckets=[-1.0, -0.8, -0.6, -0.4, -0.2, 0.0],
        registry=_prom_registry,
    )
    SCRAPE_ERRORS = Counter(
        "neuroops_scrape_errors_total",
        "Total number of Prometheus scrape errors",
        registry=_prom_registry,
    )
    MODEL_LOADED = Gauge(
        "neuroops_model_loaded",
        "1 if IsolationForest model is loaded, 0 otherwise",
        registry=_prom_registry,
    )
    LSTM_LOADED_GAUGE = Gauge(
        "neuroops_lstm_model_loaded",
        "1 if LSTM/Ridge model is loaded, 0 otherwise",
        registry=_prom_registry,
    )
    CORRELATED_GROUPS = Gauge(
        "neuroops_correlated_alert_groups",
        "Number of correlated alert groups currently active",
        registry=_prom_registry,
    )
    _prom_enabled = True
except ImportError:
    _prom_enabled = False
    _prom_registry = None
    structlog.get_logger().warning("prometheus_client not installed; detector metrics disabled")

# Configure standard console logging
structlog.configure(
    processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()]
)
logger = structlog.get_logger()

# Global instances
scraper = PrometheusScraper()
alerter = Alerter()
model = IsolationForestModel()
sequence_model = SequenceForecastModel()
correlator = AlertCorrelator(
    correlation_window_seconds=float(os.getenv("CORRELATION_WINDOW_SECONDS", "30")),
    max_age_seconds=float(os.getenv("CORRELATION_MAX_AGE_SECONDS", "300")),
)

# Active alert registry
active_alerts: list[Alert] = []
training_lock = threading.Lock()
training_in_progress = False
# Model file locations
MODEL_PATH = os.getenv("MODEL_PATH", "checkpoints/isolation_forest.joblib")
# NOTE: Despite the historical 'lstm_model.pt' filename, SequenceForecastModel
# uses Ridge Regression via joblib (not PyTorch). New default is seq_model.joblib.
# Set SEQ_MODEL_PATH env var to override (supports both .pt and .joblib files).
SEQ_MODEL_PATH = os.getenv("SEQ_MODEL_PATH", "checkpoints/seq_model.joblib")
model_loaded = False
seq_model_loaded = False
PREDICTIVE_ALERTS_ENABLED = os.getenv("PREDICTIVE_ALERTS_ENABLED", "true").lower() == "true"
forecaster = TrendForecaster()


# service_history maps service_name -> list of MetricWindow
service_history: dict[str, list[MetricWindow]] = {}


class CorrelationStatsResponse(BaseModel):
    total_buffered_alerts: int
    correlated_groups: int
    cascading_failure_groups: int
    correlation_window_seconds: float
    max_age_seconds: float


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    seq_model_loaded: bool
    active_alerts_count: int
    correlation_stats: CorrelationStatsResponse


class TrainBaselineResponse(BaseModel):
    status: str
    message: str


# Try to load IsolationForest model at startup
try:
    if os.path.exists(MODEL_PATH):
        model.load(MODEL_PATH)
        model_loaded = True
        logger.info(
            "Successfully loaded IsolationForest model checkpoint at startup", path=MODEL_PATH
        )
    else:
        logger.warn("No model checkpoint found at startup, running in Warmup Mode", path=MODEL_PATH)
except Exception as e:
    logger.error(
        "Failed to load model checkpoint at startup",
        path=MODEL_PATH,
        error=str(e),
        exc_info=True,
    )

# Try to load sequence forecaster model at startup
try:
    if os.path.exists(SEQ_MODEL_PATH):
        sequence_model.load(SEQ_MODEL_PATH)
        seq_model_loaded = True
        logger.info(
            "Successfully loaded sequence forecaster checkpoint at startup", path=SEQ_MODEL_PATH
        )
except Exception as e:
    logger.error(
        "Failed to load sequence forecaster checkpoint at startup",
        path=SEQ_MODEL_PATH,
        error=str(e),
        exc_info=True,
    )


def get_resolved_detector_config() -> dict[str, Any]:
    """Returns resolved detector configuration values for startup validation/logging."""
    return {
        "PROMETHEUS_URL": os.getenv("PROMETHEUS_URL"),
        "TARGET_NAMESPACE": os.getenv("TARGET_NAMESPACE", "neuroops-demo"),
        "ANOMALY_CONTAMINATION": os.getenv("ANOMALY_CONTAMINATION", "0.05"),
        "ALERT_DEDUP_WINDOW_SECONDS": os.getenv("ALERT_DEDUP_WINDOW_SECONDS", "300"),
        "PREDICTIVE_ALERTS_ENABLED": os.getenv("PREDICTIVE_ALERTS_ENABLED", "true"),
    }


async def validate_startup_config() -> None:
    """Validates required startup config and probes Prometheus health defensively."""
    config = get_resolved_detector_config()
    logger.info("Resolved detector startup configuration", **config)

    if not config["PROMETHEUS_URL"]:
        logger.error("Missing required detector environment variable", variable="PROMETHEUS_URL")
        raise RuntimeError("Missing required environment variable: PROMETHEUS_URL")

    health_url = f"{str(config['PROMETHEUS_URL']).rstrip('/')}/-/healthy"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(health_url)
            response.raise_for_status()
        logger.info(
            "Prometheus startup health check succeeded",
            prometheus_url=config["PROMETHEUS_URL"],
        )
    except httpx.TimeoutException as exc:
        logger.warning(
            "Prometheus startup health check timed out",
            prometheus_url=config["PROMETHEUS_URL"],
            url=health_url,
            timeout_seconds=5.0,
            error=str(exc),
        )
    except httpx.ConnectError as exc:
        logger.warning(
            "Prometheus startup health check connection failed",
            prometheus_url=config["PROMETHEUS_URL"],
            url=health_url,
            timeout_seconds=5.0,
            error=str(exc),
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Prometheus startup health check returned HTTP error",
            prometheus_url=config["PROMETHEUS_URL"],
            url=str(exc.request.url),
            status_code=exc.response.status_code,
            timeout_seconds=5.0,
            error=str(exc),
        )
    except Exception as exc:
        logger.warning(
            "Prometheus startup health check failed unexpectedly",
            prometheus_url=config["PROMETHEUS_URL"],
            url=health_url,
            timeout_seconds=5.0,
            error=str(exc),
            exc_info=True,
        )


def internal_error(detail: str) -> HTTPException:
    """Builds a structured HTTP 500 response without leaking raw exceptions."""
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": "internal_server_error", "message": detail},
    )


async def background_scraping_loop():
    """Background task running every 15 seconds to scrape metrics and evaluate anomalies."""
    global model_loaded, seq_model_loaded
    logger.info("Starting background scraping loop task")

    while True:
        current_service = None
        current_timestamp = None
        try:
            # Scrape current metric window
            windows = scraper.scrape_metrics()

            for window in windows:
                service = window.service_name
                current_service = service
                current_timestamp = window.timestamp
                if service not in service_history:
                    service_history[service] = []

                # Capture history sequence before adding this step
                sequence = list(service_history[service])

                # Append and limit history
                service_history[service].append(window)
                if len(service_history[service]) > 5:
                    service_history[service].pop(0)

                if model_loaded:
                    # Run IsolationForest Anomaly detection
                    anomaly_score = model.score(window)
                    is_anomaly = model.predict(window)

                    # Update Prometheus anomaly score histogram
                    if _prom_enabled:
                        ANOMALY_SCORE.observe(anomaly_score)

                    # Run sequence forecaster temporal verification
                    is_seq_anomaly = False
                    if seq_model_loaded and len(sequence) >= 5:
                        is_seq_anomaly = sequence_model.predict(sequence, window)

                    # Process window with alerter
                    alert = alerter.process_window(window, anomaly_score, is_anomaly)
                    if alert:
                        alerter.ensure_unique_alert_id(alert, active_alerts)
                        # Downclass points that are transient (no temporal trend detected by LSTM)
                        if seq_model_loaded and not is_seq_anomaly:
                            alert.severity = "P3"
                            logger.info(
                                "LSTM filtered transient point anomaly: downclassing alert to P3",
                                service=service,
                            )

                        # Append alert and limit registry size to prevent memory leak
                        active_alerts.append(alert)
                        if len(active_alerts) > 500:
                            active_alerts.pop(0)
                else:
                    logger.info(
                        "Scraping loop in Warmup Mode - skipping anomaly scoring", service=service
                    )

                # Run predictive alerting if enabled
                if PREDICTIVE_ALERTS_ENABLED:
                    forecaster.update(window)
                    prefault = forecaster.predict_breach(service)
                    if prefault:
                        active_alerts.append(prefault)
                        if len(active_alerts) > 500:
                            active_alerts.pop(0)

            # Feed active alerts into correlator and update Prometheus gauges
            correlator.ingest(active_alerts)
            if _prom_enabled:
                ALERTS_ACTIVE.set(len(active_alerts))
                corr_groups = correlator.correlate()
                CORRELATED_GROUPS.set(len(corr_groups))
                MODEL_LOADED.set(1 if model_loaded else 0)
                LSTM_LOADED_GAUGE.set(1 if seq_model_loaded else 0)

        except Exception as e:
            logger.error(
                "Error in background scraping loop",
                service=current_service,
                timestamp=current_timestamp,
                error=str(e),
                exc_info=True,
            )

        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await validate_startup_config()
    # Startup: Spin up background loop task
    task = asyncio.create_task(background_scraping_loop())
    yield
    # Shutdown: Cancel the background scraping task cleanly
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("Background scraping loop cancelled during detector shutdown")


app = FastAPI(title="NeuroOps Anomaly Detection Service", lifespan=lifespan)

# ── Rate limiting: 60 req/min per IP by default ───────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/alerts", response_model=list[Alert], status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
async def get_alerts(request: Request):
    """Returns the list of active/fired alerts."""
    try:
        return active_alerts
    except Exception as exc:
        logger.error("Failed to return active alerts", error=str(exc), exc_info=True)
        raise internal_error("Failed to return active alerts")


@app.get("/alerts/predictive", response_model=list[Alert], status_code=status.HTTP_200_OK)
async def get_predictive_alerts():
    """Returns only predictive alerts (type='predictive')."""
    try:
        return [a for a in active_alerts if getattr(a, "type", "reactive") == "predictive"]
    except Exception as exc:
        logger.error("Failed to return predictive alerts", error=str(exc), exc_info=True)
        raise internal_error("Failed to return predictive alerts")


@app.get("/alerts/correlated", response_model=list[CorrelatedAlert], status_code=status.HTTP_200_OK)
async def get_correlated_alerts():
    """
    Returns alerts grouped into correlated groups by temporal proximity.
    Groups that affect multiple services are flagged as is_cascading_failure=True.
    This eliminates redundant RCA investigations for the same root cause.
    """
    try:
        correlator.ingest(active_alerts)
        return correlator.correlate()
    except Exception as exc:
        logger.error("Failed to return correlated alerts", error=str(exc), exc_info=True)
        raise internal_error("Failed to return correlated alerts")


@app.get(
    "/alerts/correlation-stats",
    response_model=CorrelationStatsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_correlation_stats():
    """Returns diagnostic statistics about the alert correlator state."""
    try:
        correlator.ingest(active_alerts)
        return correlator.get_correlation_stats()
    except Exception as exc:
        logger.error("Failed to return correlation stats", error=str(exc), exc_info=True)
        raise internal_error("Failed to return correlation stats")


@app.get("/metrics", status_code=status.HTTP_200_OK)
async def prometheus_metrics():
    """Exposes Prometheus-format metrics for scraping by Grafana / kube-prometheus."""
    try:
        if not _prom_enabled:
            return Response(
                content="# prometheus_client not installed",
                media_type="text/plain",
            )
        return Response(
            content=generate_latest(_prom_registry),
            media_type=CONTENT_TYPE_LATEST,
        )
    except Exception as exc:
        logger.error("Failed to generate Prometheus metrics", error=str(exc), exc_info=True)
        raise internal_error("Failed to generate Prometheus metrics")


@app.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def get_health():
    """Returns service health status and model availability."""
    try:
        return {
            "status": "ok",
            "model_loaded": model_loaded,
            "seq_model_loaded": seq_model_loaded,
            "active_alerts_count": len(active_alerts),
            "correlation_stats": correlator.get_correlation_stats(),
        }
    except Exception as exc:
        logger.error("Failed to return detector health", error=str(exc), exc_info=True)
        raise internal_error("Failed to return detector health")


def run_async_training(minutes: int):
    """Asynchronous background training process."""
    global model_loaded, seq_model_loaded, training_in_progress
    try:
        logger.info("Asynchronous baseline training task started")
        # Query historical data from Prometheus instantly
        windows = collect_historical_baseline(scraper, minutes=minutes)
        if not windows:
            logger.error("No metrics returned from Prometheus, training aborted")
            return

        # Fit IsolationForest
        new_model = IsolationForestModel()
        new_model.fit(windows)
        new_model.save(MODEL_PATH)

        # Fit LSTM
        new_seq_model = SequenceForecastModel()
        new_seq_model.fit(windows)
        new_seq_model.save(SEQ_MODEL_PATH)

        # Swap models globally
        model.models = new_model.models
        model.features = new_model.features
        model._fitted = new_model._fitted
        model_loaded = True

        sequence_model.models = new_seq_model.models
        sequence_model.thresholds = new_seq_model.thresholds
        sequence_model.features = new_seq_model.features
        seq_model_loaded = True

        logger.info(
            "Asynchronous IsolationForest and LSTM model training and reloading "
            "completed successfully!"
        )
    except Exception as e:
        logger.error(
            "Failed in asynchronous model training process",
            duration_minutes=minutes,
            error=str(e),
            exc_info=True,
        )
    finally:
        with training_lock:
            training_in_progress = False
        logger.info("Asynchronous baseline training task finished", duration_minutes=minutes)


@app.post(
    "/baseline/train",
    response_model=TrainBaselineResponse,
    status_code=status.HTTP_200_OK,
)
async def train_baseline(background_tasks: BackgroundTasks, minutes: int = 30):
    """Triggers historical baseline query and IsolationForest training asynchronously."""
    global training_in_progress
    try:
        with training_lock:
            if training_in_progress:
                logger.warning(
                    "Rejected concurrent baseline training request",
                    duration_minutes=minutes,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Training already in progress",
                )
            training_in_progress = True

        logger.info("Received request to trigger model baseline training", duration_minutes=minutes)
        background_tasks.add_task(run_async_training, minutes)
        return {
            "status": "training_started",
            "message": (
                f"Historical data collection ({minutes}m) and training running in background."
            ),
        }
    except HTTPException:
        logger.warning(
            "Baseline training request returned HTTP exception",
            duration_minutes=minutes,
            training_in_progress=training_in_progress,
        )
        raise
    except Exception as exc:
        with training_lock:
            training_in_progress = False
        logger.error(
            "Failed to start baseline training",
            duration_minutes=minutes,
            error=str(exc),
            exc_info=True,
        )
        raise internal_error("Failed to start baseline training")
