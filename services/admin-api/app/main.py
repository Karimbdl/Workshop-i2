"""admin-api : agrège les données de supervision pour la console d'administration.

Lit les incidents repérés par le détecteur ML et l'état des services dans Prometheus,
et les expose derrière la passerelle, réservés aux rôles operator et admin.

Le moteur de remédiation n'existe pas encore : /admin/remediations renvoie une liste vide
pour l'instant, et se remplira quand le moteur sera branché.
"""

import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from resilience_common.http import client_ip, setup_http
from resilience_common.logs import log_event, setup_logging
from resilience_common.secrets import read_secret
from resilience_common.security import Principal, require_roles

SERVICE = "admin-api"
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
ML_DETECTOR_URL = os.getenv("ML_DETECTOR_URL", "http://ml-detector:8000")
REMEDIATION_URL = os.getenv("REMEDIATION_URL", "http://remediation-engine:8000")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SECONDS", "3"))

try:
    INTERNAL_TOKEN = read_secret("internal_token")
except Exception:
    INTERNAL_TOKEN = None

setup_logging(SERVICE)
logger = logging.getLogger(SERVICE)
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# Accès réservé au personnel de supervision.
staff_only = require_roles("operator", "admin")

# Noms lisibles des cibles Prometheus (clé = valeur du label job).
SERVICE_LABELS = {
    "gateway": "Passerelle / WAF",
    "auth-service": "Authentification",
    "ledger-service": "Grand livre",
    "payment-api": "Paiements",
    "ml-detector": "Détecteur ML",
    "postgres": "Base de données",
    "redis": "Cache / verrous",
    "prometheus": "Prometheus",
    "loki": "Loki",
    "alloy": "Collecte de journaux",
}

# Gravité associée à chaque type d'incident du détecteur.
GRAVITE = {
    "integrite": "élevée",
    "intrusion_applicative": "élevée",
    "force_brute": "élevée",
    "disponibilite": "moyenne",
    "surcharge": "moyenne",
    "degradation": "faible",
}

app = FastAPI(title="RESILIENCE-ALPHA admin-api")
setup_http(app)


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prom_query(expr: str):
    """Exécute une requête instantanée Prometheus et renvoie la liste des résultats."""
    url = f"{PROMETHEUS_URL}/api/v1/query"
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, params={"query": expr})
        resp.raise_for_status()
        payload = resp.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus a refusé la requête : {expr}")
    return payload["data"]["result"]


def detector_status() -> dict:
    """Récupère l'état courant du détecteur ML (incident, score, phase)."""
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(f"{ML_DETECTOR_URL}/status")
        resp.raise_for_status()
        return resp.json()


def incident_view(incident: dict | None) -> dict | None:
    """Met en forme l'incident du détecteur pour la console."""
    if not incident:
        return None
    started = incident.get("started_at", "")
    return {
        "id": "INC-" + started.replace(":", "").replace("-", "")[-8:] if started else "INC-?",
        "type": incident.get("type"),
        "label": incident.get("label"),
        "causes": incident.get("causes", []),
        "gravite": GRAVITE.get(incident.get("type"), "moyenne"),
        "started_at": started,
        "peak_score": incident.get("peak_score"),
    }


def services_state() -> list[dict]:
    """État en ligne / hors ligne de chaque cible, depuis la métrique `up` de Prometheus."""
    results = prom_query("up")
    services = []
    for row in results:
        # Les services applicatifs partagent le job « services » mais portent un label
        # `service` propre (auth-service, payment-api, ledger-service) : on le préfère.
        name = row["metric"].get("service") or row["metric"].get("job", "?")
        up = row["value"][1] == "1"
        services.append({"name": name, "label": SERVICE_LABELS.get(name, name), "up": up})
    services.sort(key=lambda s: (s["up"], s["label"]))
    return services


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"ready": True}


@app.get("/admin/overview")
def overview(principal: Principal = Depends(staff_only)):
    """Indicateurs clés de la console."""
    status = detector_status()
    incident = status.get("incident")
    services = services_state()
    up = sum(1 for s in services if s["up"])

    waf_total = None
    try:
        res = prom_query("sum(devolut_waf_events_total)")
        if res:
            waf_total = int(float(res[0]["value"][1]))
    except Exception as exc:  # métrique absente ou Prometheus indisponible : non bloquant
        log_event(logger, "waf_metric_unavailable", logging.WARNING, error=str(exc))

    ledger_frozen = None
    try:
        res = prom_query("ledger_frozen")
        if res:
            ledger_frozen = float(res[0]["value"][1]) >= 1
    except Exception as exc:
        log_event(logger, "freeze_metric_unavailable", logging.WARNING, error=str(exc))

    return {
        "detector_state": status.get("state"),
        "anomaly_score": status.get("anomaly_score"),
        "incident_active": incident is not None,
        "services_up": up,
        "services_total": len(services),
        "waf_blocked_total": waf_total,
        "ledger_frozen": ledger_frozen,
        "checked_at": _iso(),
    }


@app.get("/admin/incidents")
def incidents(principal: Principal = Depends(staff_only)):
    """Incident en cours (0 ou 1 pour l'instant : le détecteur suit un incident à la fois)."""
    status = detector_status()
    view = incident_view(status.get("incident"))
    return {
        "detector_state": status.get("state"),
        "anomaly_score": status.get("anomaly_score"),
        "incidents": [view] if view else [],
        "checked_at": _iso(),
    }


@app.get("/admin/services")
def services(principal: Principal = Depends(staff_only)):
    """État de chaque service de la plateforme."""
    return {"services": services_state(), "checked_at": _iso()}


@app.get("/admin/remediations")
def remediations(principal: Principal = Depends(staff_only)):
    """Historique des remédiations, lu depuis le moteur de remédiation."""
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.get(f"{REMEDIATION_URL}/internal/remediations",
                              headers={"X-Internal-Token": INTERNAL_TOKEN or ""})
            resp.raise_for_status()
            data = resp.json()
        return {"remediations": data.get("remediations", []), "engine_connected": True, "checked_at": _iso()}
    except Exception as exc:
        log_event(logger, "remediation_unavailable", logging.WARNING, error=str(exc))
        return {"remediations": [], "engine_connected": False, "checked_at": _iso()}


# ------------------------------------------------------------------- Actions
# Les actions privilégiées (remédiation, blocage d'IP, gel du grand livre) sont
# exécutées par le moteur de remédiation, seul détenteur du jeton interne et des
# accès Docker/ledger. admin-api ne fait que relayer, après contrôle du rôle.

ENGINE_ACTION_TIMEOUT = float(os.getenv("ENGINE_ACTION_TIMEOUT_SECONDS", "20"))


def engine_call(method: str, path: str, payload: dict | None = None, timeout: float | None = None):
    try:
        with httpx.Client(timeout=timeout or HTTP_TIMEOUT) as client:
            resp = client.request(
                method, f"{REMEDIATION_URL}{path}",
                headers={"X-Internal-Token": INTERNAL_TOKEN or ""},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        log_event(logger, "engine_call_failed", logging.WARNING, path=path, error=str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Moteur de remédiation injoignable")


class IpIn(BaseModel):
    ip: str = Field(min_length=3, max_length=45)


class FreezeIn(BaseModel):
    freeze: bool
    reason: str = Field(default="Action console", min_length=3, max_length=200)


@app.get("/admin/blocklist")
def get_blocklist(principal: Principal = Depends(staff_only)):
    """Adresses IP actuellement bloquées par la passerelle."""
    data = engine_call("GET", "/internal/blocklist")
    return {"banned": data.get("banned", []), "checked_at": _iso()}


@app.post("/admin/actions/remediate")
def action_remediate(principal: Principal = Depends(staff_only)):
    """Force une remédiation sur l'incident en cours."""
    log_event(logger, "action_remediate", by=principal.username)
    return engine_call("POST", "/internal/trigger", timeout=ENGINE_ACTION_TIMEOUT)


@app.post("/admin/actions/block-ip")
def action_block_ip(body: IpIn, request: Request, principal: Principal = Depends(staff_only)):
    # Garde-fou : ne pas bloquer l'adresse de l'opérateur lui-même (auto-déconnexion).
    if body.ip.strip() == client_ip(request):
        return {"ok": False, "detail": "Refusé : c'est votre propre adresse, vous seriez déconnecté."}
    log_event(logger, "action_block_ip", by=principal.username, ip=body.ip)
    return engine_call("POST", "/internal/block-ip", {"ip": body.ip})


@app.post("/admin/actions/unblock-ip")
def action_unblock_ip(body: IpIn, principal: Principal = Depends(staff_only)):
    log_event(logger, "action_unblock_ip", by=principal.username, ip=body.ip)
    return engine_call("POST", "/internal/unblock-ip", {"ip": body.ip})


@app.post("/admin/actions/freeze-ledger")
def action_freeze_ledger(body: FreezeIn, principal: Principal = Depends(staff_only)):
    log_event(logger, "action_freeze_ledger", by=principal.username, freeze=body.freeze)
    return engine_call("POST", "/internal/freeze-ledger", {"freeze": body.freeze, "reason": body.reason})
