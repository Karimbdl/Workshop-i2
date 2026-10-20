"""ml-detector : détection d'anomalies sur le comportement de la plateforme.

Cycle : relève les indicateurs dans Prometheus → (apprend la référence, puis) note chaque instant →
qualifie l'incident → expose un score et un incident courant. La connexion au moteur de remédiation
se fait par l'endpoint interne /internal/incident (il viendra interroger ce service).
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.concurrency import run_in_threadpool
from prometheus_client import Gauge

from resilience_common.http import setup_http
from resilience_common.internal import require_internal_token
from resilience_common.logs import log_event, setup_logging

from .classify import INCIDENTS, Z_THRESHOLD, classify
from .features import PrometheusClient
from .model import AnomalyModel

SERVICE = "ml-detector"
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))
MIN_BASELINE = int(os.getenv("MIN_BASELINE_SAMPLES", "40"))      # ~10 min à 15 s
MAX_BASELINE = int(os.getenv("MAX_BASELINE_SAMPLES", "480"))     # ~2 h glissantes
TICKS_TO_OPEN = int(os.getenv("TICKS_TO_OPEN", "2"))             # anomalies consécutives pour ouvrir
TICKS_TO_CLOSE = int(os.getenv("TICKS_TO_CLOSE", "4"))           # relevés normaux pour clore
WARMUP_TICKS = int(os.getenv("WARMUP_TICKS", "2"))               # relevés ignorés au démarrage (montée en charge)
# Marge minimale de score pour retenir une anomalie : filtre les écarts marginaux du modèle.
SCORE_MARGIN = float(os.getenv("ANOMALY_SCORE_MARGIN", "0.05"))
# Déclencheur dur : indicateurs de sécurité qui doivent faire ouvrir un incident même si le modèle
# hésite (pic bref mais net). Seuil plancher pour éviter de réagir à une valeur négligeable.
SECURITY_FEATURES = ("waf_blocks", "rate_429", "rate_403", "login_fail")
SECURITY_FLOOR = float(os.getenv("SECURITY_FLOOR", "0.2"))  # en événements/s sur 1 min (~12/min)
MODEL_PATH = Path(os.getenv("MODEL_PATH", "/app/model/anomaly.joblib"))

setup_logging(SERVICE)
logger = logging.getLogger(SERVICE)
# httpx journalise chaque requête en INFO : on ne garde que les problèmes (une relève = ~12 requêtes).
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ------------------------------------------------------------------- Métriques
STATE = Gauge("ml_state", "État du détecteur : 0 apprentissage, 1 surveillance")
BASELINE_SIZE = Gauge("ml_baseline_samples", "Relevés de référence accumulés")
ANOMALY_SCORE = Gauge("ml_anomaly_score", "Score d'anomalie du dernier relevé (plus haut = plus atypique)")
IS_ANOMALY = Gauge("ml_is_anomaly", "1 si le dernier relevé est jugé anormal")
INCIDENT_ACTIVE = Gauge("ml_incident_active", "1 si un incident est en cours")
INCIDENT_BY_TYPE = Gauge("ml_incident", "Incident en cours, par type (1 = actif)", ["type"])
FEATURE = Gauge("ml_feature", "Valeur du dernier relevé, par indicateur", ["name"])
FEATURE_Z = Gauge("ml_feature_zscore", "Écart à la référence, par indicateur (en écarts-types)", ["name"])


class Detector:
    def __init__(self):
        self.prom = PrometheusClient(PROMETHEUS_URL)
        self.model = AnomalyModel(MODEL_PATH, MIN_BASELINE, MAX_BASELINE)
        self.anomaly_streak = 0
        self.normal_streak = 0
        self.ticks = 0
        self.incident = None          # incident courant (dict) ou None
        self.last = {}                # dernier relevé + score, pour /status
        for name in INCIDENTS:
            INCIDENT_BY_TYPE.labels(name).set(0)

    def tick(self):
        self.ticks += 1
        vector = self.prom.build_vector()
        for name, value in vector.items():
            FEATURE.labels(name).set(value)

        # Phase d'apprentissage : on accumule du trafic normal puis on entraîne une fois.
        # On ignore les tout premiers relevés (montée en charge, état non représentatif).
        if not self.model.is_trained:
            STATE.set(0)
            if self.ticks <= WARMUP_TICKS:
                self.last = {"state": "préchauffage", "vector": vector}
                return
            size = self.model.add_baseline(vector)
            BASELINE_SIZE.set(size)
            if size >= MIN_BASELINE:
                self.model.train()
            self.last = {"state": "apprentissage", "baseline": size, "vector": vector}
            return

        STATE.set(1)
        score, model_flag, zscores = self.model.score(vector)
        # Trois voies d'anomalie :
        #  - signal dur : grand livre incohérent ou service à terre ;
        #  - déclencheur sécurité : un indicateur de sécurité nettement au-dessus de sa référence ;
        #  - modèle : la forêt d'isolation signale un point atypique, au-delà de la marge de score.
        hard_signal = vector.get("integrity_ok", 1) < 1 or vector.get("up_ratio", 1) < 1
        security_hit = any(
            zscores.get(name, 0) >= Z_THRESHOLD and vector.get(name, 0) >= SECURITY_FLOOR
            for name in SECURITY_FEATURES
        )
        is_anomaly = hard_signal or security_hit or (model_flag and score >= SCORE_MARGIN)
        ANOMALY_SCORE.set(score)
        IS_ANOMALY.set(1 if is_anomaly else 0)
        for name, z in zscores.items():
            FEATURE_Z.labels(name).set(z)

        # En temps normal, on continue d'enrichir la référence (dérive lente du trafic légitime).
        if not is_anomaly and self.incident is None:
            BASELINE_SIZE.set(self.model.add_baseline(vector))

        self._update_incident(vector, zscores, score, is_anomaly)
        self.last = {"state": "surveillance", "score": round(score, 4),
                     "is_anomaly": is_anomaly, "vector": vector,
                     "incident": self.incident}

    def _update_incident(self, vector, zscores, score, is_anomaly):
        if is_anomaly:
            self.anomaly_streak += 1
            self.normal_streak = 0
        else:
            self.normal_streak += 1
            self.anomaly_streak = 0

        if self.incident is None and self.anomaly_streak >= TICKS_TO_OPEN:
            itype, label, causes = classify(vector, zscores)
            self.incident = {
                "type": itype, "label": label, "causes": causes,
                "started_at": _iso(), "peak_score": round(score, 4),
            }
            INCIDENT_ACTIVE.set(1)
            INCIDENT_BY_TYPE.labels(itype).set(1)
            log_event(logger, "incident_ouvert", logging.WARNING,
                      type=itype, label=label, causes=",".join(causes), score=round(score, 4))

        elif self.incident is not None:
            self.incident["peak_score"] = max(self.incident["peak_score"], round(score, 4))
            # Réévalue le type tant que l'incident est actif (une attaque peut évoluer).
            if is_anomaly:
                itype, label, causes = classify(vector, zscores)
                if itype != self.incident["type"]:
                    INCIDENT_BY_TYPE.labels(self.incident["type"]).set(0)
                    INCIDENT_BY_TYPE.labels(itype).set(1)
                    self.incident.update(type=itype, label=label, causes=causes)
            if self.normal_streak >= TICKS_TO_CLOSE:
                closed = self.incident
                INCIDENT_ACTIVE.set(0)
                INCIDENT_BY_TYPE.labels(closed["type"]).set(0)
                log_event(logger, "incident_clos", type=closed["type"],
                          duree_depuis=closed["started_at"])
                self.incident = None

    def status(self):
        model = self.model
        return {
            "service": SERVICE,
            "state": "surveillance" if model.is_trained else "apprentissage",
            "model_trained": model.is_trained,
            "trained_at": str(model.trained_at) if model.trained_at else None,
            "baseline_samples": len(model.baseline),
            "min_baseline": MIN_BASELINE,
            "anomaly_score": self.last.get("score"),
            "is_anomaly": self.last.get("is_anomaly"),
            "incident": self.incident,
        }


detector: Detector | None = None


async def loop():
    assert detector is not None
    log_event(logger, "service_started", prometheus=PROMETHEUS_URL, interval=POLL_INTERVAL)
    while True:
        try:
            await run_in_threadpool(detector.tick)
        except Exception as exc:  # une erreur de relevé ne doit jamais tuer la boucle
            log_event(logger, "tick_failed", logging.ERROR, error=str(exc))
        await asyncio.sleep(POLL_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global detector
    detector = Detector()
    task = asyncio.create_task(loop())
    yield
    task.cancel()
    detector.prom.close()


app = FastAPI(title="RESILIENCE-ALPHA ml-detector", lifespan=lifespan)
setup_http(app)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"ready": detector is not None}


@app.get("/status")
def status():
    """Vue lisible de l'état courant (pour la console et le débogage)."""
    return detector.status()


@app.get("/internal/incident", dependencies=[Depends(require_internal_token)])
def current_incident():
    """Incident en cours, consommé par le moteur de remédiation. null si aucun."""
    return {"incident": detector.incident}


@app.post("/internal/train", dependencies=[Depends(require_internal_token)])
def retrain():
    """Force un réentraînement sur la référence accumulée."""
    ok = detector.model.train()
    return {"trained": ok, "baseline_samples": len(detector.model.baseline)}


def _iso():
    return datetime.now(timezone.utc).isoformat()
