"""Modèle de détection d'anomalies.

Approche : apprentissage non supervisé sur le comportement normal avec une forêt d'isolation
(IsolationForest), précédée d'une normalisation. On n'a pas d'exemples étiquetés d'attaques, donc
le modèle apprend seulement « ce qui est normal » et signale ce qui s'en écarte. Les statistiques
de référence (moyenne, écart-type par indicateur) sont conservées pour expliquer chaque écart.
"""

import logging
import threading
from collections import deque
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from resilience_common.logs import log_event
from .features import MODEL_FEATURE_NAMES

logger = logging.getLogger("ml-detector")


class AnomalyModel:
    def __init__(self, model_path: Path, min_baseline: int, max_baseline: int):
        self.model_path = model_path
        self.min_baseline = min_baseline
        self.feature_names = MODEL_FEATURE_NAMES
        self.pipeline = None
        self.means = None
        self.stds = None
        self.trained_at = None
        self.baseline = deque(maxlen=max_baseline)
        self.lock = threading.Lock()
        self._load()

    # ---------------------------------------------------------------- Données
    def _matrix(self, vectors) -> np.ndarray:
        return np.array([[v[name] for name in self.feature_names] for v in vectors], dtype=float)

    def add_baseline(self, vector: dict) -> int:
        """Ajoute un relevé au trafic de référence. Renvoie la taille courante du tampon."""
        with self.lock:
            self.baseline.append(vector)
            return len(self.baseline)

    @property
    def is_trained(self) -> bool:
        return self.pipeline is not None

    # ---------------------------------------------------------------- Entraînement
    def train(self) -> bool:
        with self.lock:
            if len(self.baseline) < self.min_baseline:
                return False
            matrix = self._matrix(self.baseline)

        pipeline = make_pipeline(
            StandardScaler(),
            IsolationForest(n_estimators=200, contamination=0.01, random_state=42),
        )
        pipeline.fit(matrix)
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        stds[stds < 1e-9] = 1e-9  # évite une division par zéro sur un indicateur constant

        with self.lock:
            self.pipeline = pipeline
            self.means = means
            self.stds = stds
            self.trained_at = _now()
        self._save()
        log_event(logger, "model_trained", samples=len(matrix), features=len(self.feature_names))
        return True

    # ---------------------------------------------------------------- Évaluation
    def score(self, vector: dict):
        """Renvoie (score_anomalie, est_anomalie, ecarts_z) pour un relevé.

        score_anomalie : plus il est grand, plus le point est atypique (0 ≈ normal).
        ecarts_z : écart de chaque indicateur à la référence, en nombre d'écarts-types.
        """
        if not self.is_trained:
            return 0.0, False, {}
        x = np.array([[vector[name] for name in self.feature_names]], dtype=float)
        # decision_function : positif = normal, négatif = anomalie. On inverse pour un score croissant.
        anomaly_score = float(-self.pipeline.decision_function(x)[0])
        is_anomaly = int(self.pipeline.predict(x)[0]) == -1
        zscores = {
            name: float((vector[name] - self.means[i]) / self.stds[i])
            for i, name in enumerate(self.feature_names)
        }
        return anomaly_score, is_anomaly, zscores

    # ---------------------------------------------------------------- Persistance
    def _save(self) -> None:
        try:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(
                {"pipeline": self.pipeline, "means": self.means, "stds": self.stds,
                 "trained_at": self.trained_at, "features": self.feature_names},
                self.model_path,
            )
        except OSError as exc:
            log_event(logger, "model_save_failed", logging.WARNING, error=str(exc))

    def _load(self) -> None:
        if not self.model_path.exists():
            return
        try:
            data = joblib.load(self.model_path)
            if data.get("features") != self.feature_names:
                log_event(logger, "model_discarded", logging.WARNING, reason="indicateurs différents")
                return
            self.pipeline = data["pipeline"]
            self.means = data["means"]
            self.stds = data["stds"]
            self.trained_at = data.get("trained_at")
            log_event(logger, "model_loaded", trained_at=str(self.trained_at))
        except (OSError, KeyError, ValueError) as exc:
            log_event(logger, "model_load_failed", logging.WARNING, error=str(exc))


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
