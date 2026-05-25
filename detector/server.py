import os
import asyncio
from typing import List, Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
import structlog
from scraper import PrometheusScraper, MetricWindow
from models.isolation_forest import IsolationForestModel
from models.lstm import LSTMAnomalyModel
from alerter import Alerter, Alert
from baseline_collector import collect_historical_baseline

# Configure standard console logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

# Global instances
scraper = PrometheusScraper()
alerter = Alerter()
model = IsolationForestModel()
lstm_model = LSTMAnomalyModel()

# Active alert registry
active_alerts: List[Alert] = []
# Model file locations
MODEL_PATH = os.getenv("MODEL_PATH", "checkpoints/isolation_forest.joblib")
LSTM_MODEL_PATH = os.getenv("LSTM_MODEL_PATH", "checkpoints/lstm_model.pt")
model_loaded = False
lstm_loaded = False

# service_history maps service_name -> list of MetricWindow
service_history: Dict[str, List[MetricWindow]] = {}

# Try to load IsolationForest model at startup
try:
    if os.path.exists(MODEL_PATH):
        model.load(MODEL_PATH)
        model_loaded = True
        logger.info("Successfully loaded IsolationForest model checkpoint at startup", path=MODEL_PATH)
    else:
        logger.warn("No model checkpoint found at startup, running in Warmup Mode", path=MODEL_PATH)
except Exception as e:
    logger.error("Failed to load model checkpoint at startup", path=MODEL_PATH, error=str(e))

# Try to load LSTM model at startup
try:
    if os.path.exists(LSTM_MODEL_PATH):
        lstm_model.load(LSTM_MODEL_PATH)
        lstm_loaded = True
        logger.info("Successfully loaded LSTM model checkpoint at startup", path=LSTM_MODEL_PATH)
except Exception as e:
    logger.error("Failed to load LSTM model checkpoint at startup", path=LSTM_MODEL_PATH, error=str(e))

async def background_scraping_loop():
    """Background task running every 15 seconds to scrape metrics and evaluate anomalies."""
    global model_loaded, lstm_loaded
    logger.info("Starting background scraping loop task")
    
    while True:
        try:
            # Scrape current metric window
            windows = scraper.scrape_metrics()
            
            for window in windows:
                service = window.service_name
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
                    
                    # Run LSTM temporal verification
                    is_lstm_anomaly = False
                    if lstm_loaded and len(sequence) >= 5:
                        is_lstm_anomaly = lstm_model.predict(sequence, window)
                    
                    # Process window with alerter
                    alert = alerter.process_window(window, anomaly_score, is_anomaly)
                    if alert:
                        # Downclass points that are transient (no temporal trend detected by LSTM)
                        if lstm_loaded and not is_lstm_anomaly:
                            alert.severity = "P3"
                            logger.info("LSTM filtered transient point anomaly: downclassing alert to P3", service=service)
                            
                        # Append alert and limit registry size to prevent memory leak
                        active_alerts.append(alert)
                        if len(active_alerts) > 500:
                            active_alerts.pop(0)
                else:
                    logger.info("Scraping loop in Warmup Mode - skipping anomaly scoring", service=service)
                    
        except Exception as e:
            logger.error("Error in background scraping loop", error=str(e))
            
        await asyncio.sleep(15)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Spin up background loop task
    task = asyncio.create_task(background_scraping_loop())
    yield
    # Shutdown: Cancel the background scraping task cleanly
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="NeuroOps Anomaly Detection Service", lifespan=lifespan)

@app.get("/alerts", response_model=List[Alert])
async def get_alerts():
    """Returns the list of active/fired alerts."""
    return active_alerts

@app.get("/health")
async def get_health():
    """Returns service health status and model availability."""
    return {
        "status": "ok",
        "model_loaded": model_loaded,
        "active_alerts_count": len(active_alerts)
    }

def run_async_training(minutes: int):
    """Asynchronous background training process."""
    global model_loaded, lstm_loaded
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
        new_lstm = LSTMAnomalyModel()
        new_lstm.fit(windows)
        new_lstm.save(LSTM_MODEL_PATH)
        
        # Swap models globally
        model.models = new_model.models
        model.features = new_model.features
        model_loaded = True
        
        lstm_model.models = new_lstm.models
        lstm_model.thresholds = new_lstm.thresholds
        lstm_model.features = new_lstm.features
        lstm_loaded = True
        
        logger.info("Asynchronous IsolationForest and LSTM model training and reloading completed successfully!")
    except Exception as e:
        logger.error("Failed in asynchronous model training process", error=str(e))

@app.post("/baseline/train")
async def train_baseline(background_tasks: BackgroundTasks, minutes: int = 30):
    """Triggers historical baseline query and IsolationForest training asynchronously."""
    logger.info("Received request to trigger model baseline training", duration_minutes=minutes)
    background_tasks.add_task(run_async_training, minutes)
    return {"status": "training_started", "message": f"Historical data collection ({minutes}m) and training running in background."}
