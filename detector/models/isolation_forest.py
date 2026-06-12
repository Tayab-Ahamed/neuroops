import os

import joblib
import numpy as np
import structlog
from scraper import MetricWindow
from sklearn.ensemble import IsolationForest

logger = structlog.get_logger()


class IsolationForestModel:
    def __init__(self, contamination: float = 0.05):
        self.contamination = contamination
        self.features = [
            "p50_latency",
            "p95_latency",
            "p99_latency",
            "request_rate",
            "error_rate",
            "cpu_usage",
            "memory_usage",
            "pod_restarts",
        ]
        # service_name -> IsolationForest instance
        self.models: dict[str, IsolationForest] = {}
        self._fitted: bool = False
        logger.info("Initialized IsolationForestModel wrapper", contamination=contamination)

    def _extract_features(self, window: MetricWindow) -> np.ndarray:
        """Extracts the features from a MetricWindow into a 1D numpy array."""
        vector = []
        for feature in self.features:
            vector.append(window.feature_vector.get(feature, 0.0))
        return np.array(vector).reshape(1, -1)

    def fit(self, windows: list[MetricWindow]):
        """Fits an Isolation Forest model per service using the provided baseline windows."""
        logger.info("Fitting IsolationForest models on baseline data", total_windows=len(windows))
        if not windows:
            logger.error("Cannot fit IsolationForest model with empty baseline dataset")
            raise ValueError("Cannot fit IsolationForest model: windows list is empty.")
        if len(windows) < 10:
            logger.error(
                "Cannot fit IsolationForest model with fewer than 10 samples",
                total_windows=len(windows),
            )
            raise ValueError("Cannot fit IsolationForest model: at least 10 samples are required.")

        # Group windows by service
        service_windows: dict[str, list[MetricWindow]] = {}
        for win in windows:
            if win.service_name not in service_windows:
                service_windows[win.service_name] = []
            service_windows[win.service_name].append(win)

        # Fit a model for each service
        for service, wins in service_windows.items():
            if len(wins) < 5:
                logger.warn(
                    "Too few samples to train model for service",
                    service=service,
                    sample_count=len(wins),
                )
                continue

            # Extract features as 2D array
            X = np.vstack([self._extract_features(w) for w in wins])

            # Initialize and fit IsolationForest
            clf = IsolationForest(contamination=self.contamination, random_state=42)
            clf.fit(X)
            self.models[service] = clf
            logger.info("Trained model for service", service=service, shape=X.shape)
        self._fitted = True

    def score(self, window: MetricWindow) -> float:
        """Returns the anomaly score for the window (-1 to 0, lower = more anomalous).

        If no model is trained for this service, returns 0.0 (normal).
        """
        service = window.service_name
        clf = self.models.get(service)
        if not clf:
            # If no model is trained yet, treat as normal
            return 0.0

        X = self._extract_features(window)
        # score_samples returns negative anomaly score. The lower, the more abnormal.
        # It's usually in range [-1.0, 0.0] or similar.
        score_val = float(clf.score_samples(X)[0])
        return score_val

    def predict(self, window: MetricWindow) -> bool:
        """Predicts whether the window is anomalous. Returns True if anomalous, False otherwise."""
        if not self._fitted:
            logger.error(
                "Cannot predict before IsolationForest model is fitted",
                service=window.service_name,
                timestamp=window.timestamp,
            )
            raise RuntimeError("Model not fitted. Call fit() first.")
        service = window.service_name
        clf = self.models.get(service)
        if not clf:
            return False

        X = self._extract_features(window)
        # IsolationForest predict returns -1 for anomaly, 1 for normal
        prediction = clf.predict(X)[0]
        is_anomaly = bool(prediction == -1)
        return is_anomaly

    def save(self, path: str):
        """Serializes and saves the models dictionary to the specified path."""
        logger.info("Saving IsolationForestModel checkpoints", path=path)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        joblib.dump(
            {"contamination": self.contamination, "features": self.features, "models": self.models},
            path,
        )

    def load(self, path: str):
        """Deserializes and loads the models from the specified path."""
        logger.info("Loading IsolationForestModel checkpoints", path=path)
        if not os.path.exists(path):
            full_path = os.path.abspath(path)
            logger.error("IsolationForest checkpoint file not found", path=full_path)
            raise FileNotFoundError(f"Model file not found at {full_path}")

        try:
            data = joblib.load(path)
        except (OSError, EOFError, ValueError, TypeError, ImportError) as exc:
            logger.error(
                "Failed to load IsolationForest checkpoint",
                path=os.path.abspath(path),
                error=str(exc),
                exc_info=True,
            )
            raise RuntimeError(f"Failed to load IsolationForest model from {path}: {exc}") from exc
        self.contamination = data.get("contamination", 0.05)
        self.features = data.get("features", self.features)
        self.models = data.get("models", {})
        self._fitted = True
        logger.info("Successfully loaded models", services=list(self.models.keys()))
