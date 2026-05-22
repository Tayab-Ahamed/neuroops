import os
import asyncio
from typing import List, Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
import structlog
from scraper import PrometheusScraper, MetricWindow
from models.isolation_forest import IsolationForestModel
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

# FastAPI app will be initialized below after defining lifespan context manager

# Global instances
scraper = PrometheusScraper()
alerter = Alerter()
model = IsolationForestModel()

# Active alert registry
active_alerts: List[Alert] = []
# Model file location
MODEL_PATH = os.getenv("MODEL_PATH", "checkpoints/isolation_forest.joblib")
model_loaded = False

# Try to load model at startup
try:
    if os.path.exists(MODEL_PATH):
        model.load(MODEL_PATH)
        model_loaded = True
        logger.info("Successfully loaded IsolationForest model checkpoint at startup", path=MODEL_PATH)
    else:
        logger.warn("No model checkpoint found at startup, running in Warmup Mode", path=MODEL_PATH)
except Exception as e:
    logger.error("Failed to load model checkpoint at startup", path=MODEL_PATH, error=str(e))

async def background_scraping_loop():
    """Background task running every 15 seconds to scrape metrics and evaluate anomalies."""
    global model_loaded
    logger.info("Starting background scraping loop task")
    
    while True:
        try:
            # Scrape current metric window
            windows = scraper.scrape_metrics()
            
            for window in windows:
                if model_loaded:
                    # Run anomaly detection
                    anomaly_score = model.score(window)
                    is_anomaly = model.predict(window)
                    
                    # Process window with alerter
                    alert = alerter.process_window(window, anomaly_score, is_anomaly)
                    if alert:
                        # Append alert and limit registry size to prevent memory leak
                        active_alerts.append(alert)
                        if len(active_alerts) > 500:
                            active_alerts.pop(0)
                else:
                    logger.info("Scraping loop in Warmup Mode - skipping anomaly scoring", service=window.service_name)
                    
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
    global model_loaded
    try:
        logger.info("Asynchronous baseline training task started")
        # Query historical data from Prometheus instantly
        windows = collect_historical_baseline(scraper, minutes=minutes)
        if not windows:
            logger.error("No metrics returned from Prometheus, training aborted")
            return
        
        # Fit model
        new_model = IsolationForestModel()
        new_model.fit(windows)
        
        # Save checkpoints
        new_model.save(MODEL_PATH)
        
        # Swap model globally
        model.models = new_model.models
        model.features = new_model.features
        model_loaded = True
        logger.info("Asynchronous model training and reloading completed successfully!")
    except Exception as e:
        logger.error("Failed in asynchronous model training process", error=str(e))

@app.post("/baseline/train")
async def train_baseline(background_tasks: BackgroundTasks, minutes: int = 30):
    """Triggers historical baseline query and IsolationForest training asynchronously."""
    logger.info("Received request to trigger model baseline training", duration_minutes=minutes)
    background_tasks.add_task(run_async_training, minutes)
    return {"status": "training_started", "message": f"Historical data collection ({minutes}m) and training running in background."}
