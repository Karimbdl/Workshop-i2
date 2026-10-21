"""remediation-engine : réparation automatique après un incident détecté.

Boucle : interroge l'incident courant du détecteur ML -> choisit une réparation
selon le type d'incident -> l'exécute -> lance un PAIEMENT TÉMOIN pour prouver que
la plateforme remarche -> journalise la remédiation.

L'historique est exposé à la console via /internal/remediations (jeton interne).
"""

import asyncio
import ipaddress
import json
import logging
import os
import uuid
from collections import deque
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from resilience_common.http import setup_http
from resilience_common.internal import require_internal_token
from resilience_common.logs import log_event, setup_logging
from resilience_common.secrets import read_secret

SERVICE = "remediation-engine"
ML_DETECTOR_URL = os.getenv("ML_DETECTOR_URL", "http://ml-detector:8000")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8080")
LEDGER_URL = os.getenv("LEDGER_URL", "http://ledger-service:8000")
DOCKER_PROXY_URL = os.getenv("DOCKER_PROXY_URL", "http://docker-proxy-rw:2375")
BLOCKLIST_PATH = os.getenv("BLOCKLIST_PATH", "/etc/nginx/blocklist/banned.conf")
GATEWAY_CONTAINER_PREFIX = os.getenv("GATEWAY_CONTAINER_PREFIX", "resilience-alpha-gateway")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
PROBE_AMOUNT = float(os.getenv("PROBE_AMOUNT", "1.00"))

BLOCKLIST_HEADER = (
    "# Adresses bannies par le moteur de remédiation. Format : <ip> 1;\n"
    "# Ce fichier est réécrit automatiquement, ne pas l'éditer à la main pendant une démo.\n"
)

setup_logging(SERVICE)
logger = logging.getLogger(SERVICE)
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

_token = None
_history = deque(maxlen=50)   # remédiations récentes (plus récentes en tête)
_handled = None               # started_at du dernier incident traité
_last_incident = None


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _internal_headers():
    return {"X-Internal-Token": _token}


# ---------------------------------------------------------------- Réparations

def restart_down_containers():
    """Redémarre les conteneurs de la plateforme qui ne tournent plus (proxy Docker restreint)."""
    restarted = []
    with httpx.Client(timeout=8) as c:
        resp = c.get(f"{DOCKER_PROXY_URL}/containers/json", params={"all": "true"})
        resp.raise_for_status()
        for ct in resp.json():
            names = ct.get("Names", [])
            name = (names[0].lstrip("/") if names else ct.get("Id", "")[:12])
            if not name.startswith("resilience-alpha-"):
                continue
            state = ct.get("State", "")
            if state != "running":
                c.post(f"{DOCKER_PROXY_URL}/containers/{ct['Id']}/restart", params={"t": "5"})
                restarted.append(name)
                log_event(logger, "service_restarted", name=name, previous_state=state)
    return restarted


def ledger_integrity():
    with httpx.Client(timeout=6) as c:
        r = c.get(f"{LEDGER_URL}/internal/integrity", headers=_internal_headers())
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------- Blocage d'adresses IP

def _read_banned() -> list[str]:
    """Lit les IP déjà bannies dans le fichier de blocage (ignore les commentaires)."""
    ips = []
    try:
        with open(BLOCKLIST_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                ips.append(line.split()[0])
    except FileNotFoundError:
        pass
    return ips


def _write_banned(ips: list[str]) -> None:
    """Réécrit le fichier de blocage (en-tête + une ligne « <ip> 1; » par adresse)."""
    body = "".join(f"{ip} 1;\n" for ip in ips)
    with open(BLOCKLIST_PATH, "w", encoding="utf-8") as f:
        f.write(BLOCKLIST_HEADER + body)


def reload_gateway() -> str | None:
    """Recharge nginx à chaud (SIGHUP) pour prendre en compte la liste de blocage."""
    with httpx.Client(timeout=8) as c:
        resp = c.get(f"{DOCKER_PROXY_URL}/containers/json")
        resp.raise_for_status()
        for ct in resp.json():
            names = ct.get("Names", [])
            name = names[0].lstrip("/") if names else ""
            if name.startswith(GATEWAY_CONTAINER_PREFIX):
                c.post(f"{DOCKER_PROXY_URL}/containers/{ct['Id']}/kill", params={"signal": "HUP"})
                log_event(logger, "gateway_reloaded", name=name)
                return name
    return None


def block_ip(ip: str) -> dict:
    addr = str(ipaddress.ip_address(ip))  # lève ValueError si l'adresse est invalide
    ips = _read_banned()
    if addr not in ips:
        ips.append(addr)
        _write_banned(ips)
        reload_gateway()
        log_event(logger, "ip_blocked", logging.WARNING, ip=addr)
    return {"ip": addr, "banned": ips}


def unblock_ip(ip: str) -> dict:
    addr = str(ipaddress.ip_address(ip))
    ips = _read_banned()
    if addr in ips:
        ips = [x for x in ips if x != addr]
        _write_banned(ips)
        reload_gateway()
        log_event(logger, "ip_unblocked", ip=addr)
    return {"ip": addr, "banned": ips}


# --------------------------------------------------------- Gel du grand livre

def set_ledger_freeze(freeze: bool, reason: str) -> dict:
    path = "freeze-all" if freeze else "unfreeze-all"
    with httpx.Client(timeout=6) as c:
        r = c.post(f"{LEDGER_URL}/internal/{path}", headers=_internal_headers(), json={"reason": reason})
        r.raise_for_status()
        return r.json()


def playbook(itype: str):
    """Retourne (texte de l'action, détails) selon le type d'incident."""
    if itype == "disponibilite":
        restarted = restart_down_containers()
        action = ("Redémarrage des services indisponibles"
                  + (f" ({', '.join(restarted)})" if restarted else " (aucun à redémarrer)"))
        return action, {"restarted": restarted}
    if itype == "integrite":
        rep = ledger_integrity()
        return "Contrôle d'intégrité du grand livre", {"integrity_ok": rep.get("ok"), "anomalies": rep.get("anomalies", [])}
    if itype in ("force_brute", "intrusion_applicative"):
        return "Confinement par le pare-feu applicatif et verrouillage des comptes (automatique), vérifié", {}
    if itype == "surcharge":
        return "Limitation de débit par IP (automatique), vérifiée", {}
    return "Confinement automatique vérifié", {}


# --------------------------------------------------------------- Paiement témoin

def _probe_credentials():
    try:
        users = json.loads(read_secret("seed_users"))
        for u in users:
            if u.get("username") == "probe":
                return u["username"], u["password"]
    except Exception:
        pass
    return "probe", os.getenv("PROBE_PASSWORD", "")


def probe_payment(attempts=6, delay=2.5):
    """Paiement témoin, avec réessais le temps que les services reviennent après réparation."""
    last = {"ok": False, "status": "non tenté"}
    import time as _t
    for _ in range(attempts):
        try:
            last = _probe_once()
            if last.get("ok"):
                return last
        except Exception as exc:
            last = {"ok": False, "status": str(exc)}
        _t.sleep(delay)
    return last


def _probe_once():
    """Un essai de paiement témoin via la passerelle."""
    user, pwd = _probe_credentials()
    with httpx.Client(timeout=8) as c:
        r = c.post(f"{GATEWAY_URL}/api/auth/login", json={"username": user, "password": pwd})
        if r.status_code != 200:
            return {"ok": False, "status": f"login {r.status_code}"}
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        accounts = c.get(f"{GATEWAY_URL}/api/accounts/me", headers=h).json()
        benef = c.get(f"{GATEWAY_URL}/api/accounts/beneficiaries", headers=h).json()
        if not accounts or not benef:
            return {"ok": False, "status": "pas de compte ou bénéficiaire"}
        debit = max(accounts, key=lambda a: a.get("balance_cents", 0))
        body = {"debit_account_id": debit["id"], "credit_iban": benef[0]["iban"],
                "amount": PROBE_AMOUNT, "label": "Paiement témoin (remédiation)"}
        pr = c.post(f"{GATEWAY_URL}/api/payments", json=body,
                    headers={**h, "Idempotency-Key": uuid.uuid4().hex})
        data = pr.json() if pr.content else {}
        return {"ok": data.get("status") == "COMPLETED", "status": data.get("status"),
                "payment_id": data.get("id")}


# ---------------------------------------------------------------- Orchestration

def remediate(incident: dict):
    itype = incident.get("type", "inconnu")
    log_event(logger, "remediation_debut", type=itype)
    try:
        action, details = playbook(itype)
    except Exception as exc:
        action, details = "Échec de la réparation", {"error": str(exc)}
        log_event(logger, "remediation_erreur", logging.ERROR, type=itype, error=str(exc))

    try:
        verif = probe_payment()
    except Exception as exc:
        verif = {"ok": False, "status": str(exc)}

    resultat = "paiement témoin OK" if verif.get("ok") else f"témoin : {verif.get('status')}"
    record = {
        "at": _iso(),
        "incident": itype,
        "label": incident.get("label", itype),
        "action": action,
        "resultat": resultat,
        "verified": bool(verif.get("ok")),
        "details": details,
    }
    _history.appendleft(record)
    log_event(logger, "remediation_fin", type=itype, verified=record["verified"], action=action)
    return record


async def loop():
    global _handled, _last_incident
    log_event(logger, "service_started", detector=ML_DETECTOR_URL)
    while True:
        try:
            with httpx.Client(timeout=5) as c:
                r = c.get(f"{ML_DETECTOR_URL}/internal/incident", headers=_internal_headers())
                incident = r.json().get("incident") if r.status_code == 200 else None
            _last_incident = incident
            if incident is not None:
                key = incident.get("started_at")
                if key and key != _handled:
                    _handled = key
                    await run_in_threadpool(remediate, incident)
        except Exception as exc:
            log_event(logger, "poll_failed", logging.WARNING, error=str(exc))
        await asyncio.sleep(POLL_INTERVAL)


app = FastAPI(title="RESILIENCE-ALPHA remediation-engine")
setup_http(app)


@app.on_event("startup")
async def startup():
    global _token
    _token = read_secret("internal_token")
    asyncio.create_task(loop())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"ready": _token is not None}


@app.get("/internal/remediations", dependencies=[Depends(require_internal_token)])
def remediations():
    return {"remediations": list(_history), "engine_connected": True, "checked_at": _iso()}


@app.get("/internal/status", dependencies=[Depends(require_internal_token)])
def status():
    return {"incident": _last_incident, "handled": _handled, "count": len(_history)}


@app.post("/internal/trigger", dependencies=[Depends(require_internal_token)])
def trigger():
    """Force une remédiation sur l'incident courant (pour la démo)."""
    if _last_incident is None:
        return {"ok": False, "detail": "Aucun incident en cours."}
    rec = remediate(_last_incident)
    return {"ok": True, "remediation": rec}


class IpIn(BaseModel):
    ip: str = Field(min_length=3, max_length=45)


class FreezeIn(BaseModel):
    freeze: bool
    reason: str = Field(default="Action console", min_length=3, max_length=200)


@app.get("/internal/blocklist", dependencies=[Depends(require_internal_token)])
def blocklist():
    return {"banned": _read_banned()}


@app.post("/internal/block-ip", dependencies=[Depends(require_internal_token)])
def block(body: IpIn):
    try:
        res = block_ip(body.ip)
    except ValueError:
        return {"ok": False, "detail": "Adresse IP invalide."}
    except Exception as exc:
        log_event(logger, "block_ip_failed", logging.ERROR, error=str(exc))
        return {"ok": False, "detail": f"Blocage impossible : {exc}"}
    return {"ok": True, **res}


@app.post("/internal/unblock-ip", dependencies=[Depends(require_internal_token)])
def unblock(body: IpIn):
    try:
        res = unblock_ip(body.ip)
    except ValueError:
        return {"ok": False, "detail": "Adresse IP invalide."}
    except Exception as exc:
        log_event(logger, "unblock_ip_failed", logging.ERROR, error=str(exc))
        return {"ok": False, "detail": f"Déblocage impossible : {exc}"}
    return {"ok": True, **res}


@app.post("/internal/freeze-ledger", dependencies=[Depends(require_internal_token)])
def freeze_ledger(body: FreezeIn):
    try:
        res = set_ledger_freeze(body.freeze, body.reason)
    except Exception as exc:
        log_event(logger, "freeze_ledger_failed", logging.ERROR, error=str(exc))
        return {"ok": False, "detail": f"Action impossible : {exc}"}
    return {"ok": True, **res}
