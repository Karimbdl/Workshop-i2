"""Indicateurs lus dans Prometheus pour décrire le comportement de la plateforme.

Chaque indicateur est une requête PromQL instantanée. Prometheus agrège déjà tout, y compris
les compteurs issus des journaux (passerelle, pare-feu) calculés par Alloy. Le détecteur n'a donc
besoin que d'un accès réseau à Prometheus, et d'aucun accès direct aux services ni à la base.
"""

import logging
import math

import httpx

from resilience_common.logs import log_event

logger = logging.getLogger("ml-detector")

# Indicateurs « comportementaux » : ils servent à entraîner le modèle d'anomalies.
MODEL_FEATURES = [
    ("req_rate",     'sum(rate(devolut_gateway_requests_total[1m])) or vector(0)'),
    ("err_ratio",    'devolut:gateway_error_ratio:rate1m or vector(0)'),
    ("rate_4xx",     'sum(rate(devolut_gateway_requests_total{status=~"4.."}[1m])) or vector(0)'),
    ("rate_429",     'sum(rate(devolut_gateway_requests_total{status="429"}[1m])) or vector(0)'),
    ("rate_403",     'sum(rate(devolut_gateway_requests_total{status="403"}[1m])) or vector(0)'),
    ("waf_blocks",   'sum(rate(devolut_waf_blocked_total[1m])) or vector(0)'),
    ("login_fail",   'sum(rate(auth_login_attempts_total{result!="success"}[1m])) or vector(0)'),
    ("latency_p95",  'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{job="services"}[1m])))'),
    ("payment_rate", 'sum(rate(payments_total[2m])) or vector(0)'),
    ("pending",      'sum(payments_pending) or vector(0)'),
]

# Indicateurs « durs » : état binaire, utilisés pour qualifier l'incident (pas pour le modèle).
SIGNAL_FEATURES = [
    ("integrity_ok", 'min(ledger_integrity_ok) or vector(1)'),
    ("anomalies",    'sum(ledger_integrity_anomalies) or vector(0)'),
    ("up_ratio",     'avg(up{job=~"services|gateway|postgres|redis"}) or vector(1)'),
]

ALL_FEATURES = MODEL_FEATURES + SIGNAL_FEATURES
MODEL_FEATURE_NAMES = [name for name, _ in MODEL_FEATURES]


class PrometheusClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=5.0)

    def query(self, expr: str) -> float:
        """Exécute une requête instantanée et renvoie une valeur scalaire (0.0 si vide ou erreur)."""
        try:
            resp = self.client.get(f"{self.base_url}/api/v1/query", params={"query": expr})
            resp.raise_for_status()
            result = resp.json()["data"]["result"]
            if not result:
                return 0.0
            value = float(result[0]["value"][1])
            return 0.0 if math.isnan(value) or math.isinf(value) else value
        except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
            log_event(logger, "prometheus_query_failed", logging.WARNING, expr=expr, error=str(exc))
            return 0.0

    def build_vector(self) -> dict[str, float]:
        """Relève tous les indicateurs et renvoie un vecteur {nom: valeur}."""
        return {name: self.query(expr) for name, expr in ALL_FEATURES}

    def close(self) -> None:
        self.client.close()
