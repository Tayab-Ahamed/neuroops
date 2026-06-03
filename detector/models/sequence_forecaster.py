import os

import joblib
import numpy as np
import structlog
from scraper import MetricWindow
from sklearn.linear_model import Ridge

logger = structlog.get_logger()


class SequenceForecastModel:
    """Ridge Regression autoregressive sequence forecaster.

    Predicts the next metric step from a rolling window of past observations
    and flags anomalies when prediction error exceeds a learned threshold.
    """

    def __init__(self, sequence_length: int = 5, alpha: float = 1.0, **kwargs):
        self.sequence_length = sequence_length
        self.alpha = alpha
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
        self.input_size = len(self.features)

        # service_name -> Ridge model
        self.models: dict[str, Ridge] = {}
        # service_name -> threshold value (mean MSE + 3 * std MSE on baseline)
        self.thresholds: dict[str, float] = {}

        logger.info(
            "Initialized sequence predictor model",
            sequence_length=sequence_length,
            features=self.features,
        )

    def _extract_features(self, window: MetricWindow) -> np.ndarray:
        vector = []
        for feature in self.features:
            vector.append(window.feature_vector.get(feature, 0.0))
        return np.array(vector, dtype=np.float32)

    def _prepare_sequences(self, windows: list[MetricWindow]) -> tuple[np.ndarray, np.ndarray]:
        """Converts raw list of windows into sequential lag inputs (X) and next-step targets (Y)."""
        X, Y = [], []
        for i in range(len(windows) - self.sequence_length):
            # Flatten the sequence of windows into a single 1D feature vector
            seq = np.concatenate(
                [self._extract_features(windows[i + j]) for j in range(self.sequence_length)]
            )
            target = self._extract_features(windows[i + self.sequence_length])
            X.append(seq)
            Y.append(target)
        return np.array(X, dtype=np.float32), np.array(Y, dtype=np.float32)

    def fit(self, windows: list[MetricWindow]):
        """Fits a sequential model per service on healthy baseline sequences."""
        logger.info("Fitting sequence models on baseline metrics", total_windows=len(windows))

        # Group windows by service
        service_windows: dict[str, list[MetricWindow]] = {}
        for win in windows:
            if win.service_name not in service_windows:
                service_windows[win.service_name] = []
            service_windows[win.service_name].append(win)

        for service, wins in service_windows.items():
            if len(wins) < self.sequence_length + 5:
                logger.warn(
                    "Too few baseline samples to train sequence predictor",
                    service=service,
                    sample_count=len(wins),
                )
                continue

            X, Y = self._prepare_sequences(wins)

            # Train Ridge Regression to predict next metric step from lags
            model = Ridge(alpha=self.alpha)
            model.fit(X, Y)

            # Compute baseline thresholds (mean MSE + 3 * std MSE)
            preds = model.predict(X)
            errors = np.mean((preds - Y) ** 2, axis=1)
            mean_err = np.mean(errors)
            std_err = np.std(errors)

            self.thresholds[service] = float(mean_err + 3.0 * max(std_err, 0.001))
            self.models[service] = model

            logger.info(
                "Trained sequence model successfully",
                service=service,
                threshold=self.thresholds[service],
            )

    def score(self, sequence: list[MetricWindow], next_window: MetricWindow) -> float:
        """Returns the MSE forecasting error for the next window given the previous sequence."""
        if not sequence or len(sequence) < self.sequence_length:
            return 0.0

        service = next_window.service_name
        model = self.models.get(service)
        if not model:
            return 0.0

        target = self._extract_features(next_window)
        seq_features = np.concatenate(
            [self._extract_features(w) for w in sequence[-self.sequence_length :]]
        )

        # Reshape for single prediction
        X = seq_features.reshape(1, -1)
        pred = model.predict(X)[0]

        mse = float(np.mean((pred - target) ** 2))
        return mse

    def predict(self, sequence: list[MetricWindow], next_window: MetricWindow) -> bool:
        """Predicts whether the next window is a sequential anomaly based on threshold exceedance."""
        service = next_window.service_name
        model = self.models.get(service)
        threshold = self.thresholds.get(service)
        if not model or threshold is None:
            return False

        mse = self.score(sequence, next_window)
        is_anom = mse > threshold
        if is_anom:
            logger.warn("Sequence anomaly detected", service=service, mse=mse, threshold=threshold)
        return is_anom

    def save(self, path: str):
        """Saves weights and parameters of all service models."""
        logger.info("Saving sequence models checkpoint", path=path)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        joblib.dump(
            {
                "thresholds": self.thresholds,
                "features": self.features,
                "sequence_length": self.sequence_length,
                "models": self.models,
            },
            path,
        )

    def load(self, path: str):
        """Loads weights and parameters of all service models."""
        logger.info("Loading sequence models checkpoint", path=path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model checkpoint not found at {path}")

        data = joblib.load(path)
        self.thresholds = data.get("thresholds", {})
        self.features = data.get("features", self.features)
        self.sequence_length = data.get("sequence_length", self.sequence_length)
        self.models = data.get("models", {})

        logger.info("Successfully loaded sequence models", services=list(self.models.keys()))
