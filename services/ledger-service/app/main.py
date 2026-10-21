"""ledger-service : comptes, soldes et grand livre en partie double."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from resilience_common.db import db_is_ready, make_engine, make_session_factory, wait_for_db
from resilience_common.http import setup_http
from resilience_common.internal import require_internal_token
from resilience_common.logs import log_event, setup_logging
from resilience_common.security import Principal, current_principal

from .ledger import LedgerError, execute_transfer, integrity_report
from .models import Account, Base
from .seed import PROBE_IBAN, seed_accounts

SERVICE = "ledger-service"
INTEGRITY_INTERVAL = int(os.getenv("INTEGRITY_CHECK_SECONDS", "30"))

setup_logging(SERVICE)
logger = logging.getLogger(SERVICE)

engine = make_engine("ledger_svc", "db_ledger_password", "ledger")
SessionLocal = make_session_factory(engine)

TRANSFERS = Counter("ledger_transfers_total", "Virements traités par le grand livre", ["result"])
INTEGRITY_OK = Gauge("ledger_integrity_ok", "1 si le grand livre est cohérent, 0 sinon")
INTEGRITY_ANOMALIES = Gauge("ledger_integrity_anomalies", "Nombre d'anomalies détectées dans le grand livre")
FROZEN = Gauge("ledger_frozen", "1 si le grand livre est gelé (aucun virement accepté), 0 sinon")

# Gel global : mesure d'urgence déclenchée depuis la console. Tant qu'il est actif,
# tous les virements sont refusés (423). L'état est en mémoire : un redémarrage le lève.
_freeze = {"on": False, "reason": None}
FROZEN.set(0)


def run_integrity_check() -> dict:
    with SessionLocal() as session:
        report = integrity_report(session)
    INTEGRITY_OK.set(1 if report["ok"] else 0)
    INTEGRITY_ANOMALIES.set(len(report["anomalies"]))
    if not report["ok"]:
        log_event(logger, "ledger_integrity_failed", logging.ERROR, anomalies=report["anomalies"])
    return report


async def integrity_loop() -> None:
    while True:
        try:
            await run_in_threadpool(run_integrity_check)
        except Exception as exc:  # la base peut être indisponible pendant un incident
            INTEGRITY_OK.set(0)
            log_event(logger, "ledger_integrity_unavailable", logging.WARNING, error=str(exc))
        await asyncio.sleep(INTEGRITY_INTERVAL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_db(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_accounts(session)
    task = asyncio.create_task(integrity_loop())
    log_event(logger, "service_started")
    yield
    task.cancel()


app = FastAPI(title="RESILIENCE-ALPHA ledger-service", version="1.0.0", lifespan=lifespan)
setup_http(app)


def account_view(acc: Account, full: bool = True) -> dict:
    view = {"id": str(acc.id), "label": acc.label, "iban": acc.iban, "currency": acc.currency}
    if full:
        view.update(
            {
                "balance_cents": acc.balance_cents,
                "balance": f"{acc.balance_cents / 100:.2f}",
                "status": acc.status,
                "kind": acc.kind,
            }
        )
    return view


@app.get("/accounts/me")
def my_accounts(principal: Principal = Depends(current_principal)):
    with SessionLocal() as session:
        accounts = session.scalars(
            select(Account).where(Account.owner_id == uuid.UUID(principal.user_id)).order_by(Account.label)
        ).all()
    return [account_view(a) for a in accounts]


@app.get("/accounts/beneficiaries")
def beneficiaries(principal: Principal = Depends(current_principal)):
    with SessionLocal() as session:
        accounts = session.scalars(
            select(Account)
            .where(Account.kind != "SYSTEM", Account.status == "ACTIVE", Account.iban != PROBE_IBAN)
            .where((Account.owner_id.is_(None)) | (Account.owner_id != uuid.UUID(principal.user_id)))
            .order_by(Account.kind, Account.label)
        ).all()
    return [account_view(a, full=False) for a in accounts]


class TransferIn(BaseModel):
    transfer_id: uuid.UUID
    owner_id: uuid.UUID
    debit_account_id: uuid.UUID
    credit_iban: str = Field(pattern=r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
    amount_cents: int = Field(gt=0, le=10_000_000)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    reference: str = Field(default="", max_length=140)


@app.post("/internal/transfers", dependencies=[Depends(require_internal_token)])
def create_transfer(body: TransferIn):
    if _freeze["on"]:
        TRANSFERS.labels("frozen").inc()
        log_event(logger, "transfer_refused_frozen", logging.WARNING, transfer_id=str(body.transfer_id))
        return JSONResponse(
            status_code=status.HTTP_423_LOCKED,
            content={"code": "ledger_frozen", "detail": "Grand livre gelé, virement refusé"},
        )
    with SessionLocal() as session:
        try:
            result = execute_transfer(
                session,
                transfer_id=body.transfer_id,
                owner_id=body.owner_id,
                debit_account_id=body.debit_account_id,
                credit_iban=body.credit_iban,
                amount_cents=body.amount_cents,
                currency=body.currency,
                reference=body.reference,
            )
            session.commit()
        except LedgerError as err:
            session.rollback()
            TRANSFERS.labels(err.code).inc()
            log_event(logger, "transfer_rejected", logging.WARNING, transfer_id=str(body.transfer_id), reason=err.code)
            return JSONResponse(status_code=err.http_status, content={"code": err.code, "detail": err.message})
        except IntegrityError as exc:
            # Cas attendu : deux appels simultanés avec le même identifiant (le second sera rejoué).
            session.rollback()
            TRANSFERS.labels("retry_conflict").inc()
            log_event(
                logger, "transfer_integrity_error", logging.WARNING,
                transfer_id=str(body.transfer_id), error=str(exc.orig)[:300],
            )
            raise HTTPException(status.HTTP_409_CONFLICT, "Virement en cours de traitement, réessayez")

    TRANSFERS.labels("completed" if result.created else "replayed").inc()
    log_event(
        logger,
        "transfer_completed" if result.created else "transfer_replayed",
        transfer_id=str(body.transfer_id),
        amount_cents=body.amount_cents,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        content={
            "transfer_id": str(result.transfer.id),
            "status": "COMPLETED",
            "debit_balance_cents": result.debit_balance_cents,
        },
    )


@app.get("/internal/integrity", dependencies=[Depends(require_internal_token)])
def integrity():
    return run_integrity_check()


class FreezeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


def set_account_status(iban: str, new_status: str, reason: str) -> dict:
    with SessionLocal() as session:
        account = session.scalar(select(Account).where(Account.iban == iban).with_for_update())
        if account is None or account.kind == "SYSTEM":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte introuvable")
        account.status = new_status
        session.commit()
    log_event(logger, "account_status_changed", logging.WARNING, iban=iban, status=new_status, reason=reason)
    return {"iban": iban, "status": new_status}


@app.post("/internal/accounts/{iban}/freeze", dependencies=[Depends(require_internal_token)])
def freeze(iban: str, body: FreezeIn):
    return set_account_status(iban, "FROZEN", body.reason)


@app.post("/internal/accounts/{iban}/unfreeze", dependencies=[Depends(require_internal_token)])
def unfreeze(iban: str, body: FreezeIn):
    return set_account_status(iban, "ACTIVE", body.reason)


@app.get("/internal/freeze-status", dependencies=[Depends(require_internal_token)])
def freeze_status():
    return {"frozen": _freeze["on"], "reason": _freeze["reason"]}


@app.post("/internal/freeze-all", dependencies=[Depends(require_internal_token)])
def freeze_all(body: FreezeIn):
    """Gèle tout le grand livre : plus aucun virement n'est accepté."""
    _freeze["on"] = True
    _freeze["reason"] = body.reason
    FROZEN.set(1)
    log_event(logger, "ledger_frozen", logging.WARNING, reason=body.reason)
    return {"frozen": True, "reason": body.reason}


@app.post("/internal/unfreeze-all", dependencies=[Depends(require_internal_token)])
def unfreeze_all(body: FreezeIn):
    """Lève le gel global : les virements reprennent."""
    _freeze["on"] = False
    _freeze["reason"] = body.reason
    FROZEN.set(0)
    log_event(logger, "ledger_unfrozen", reason=body.reason)
    return {"frozen": False, "reason": body.reason}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    ok = db_is_ready(engine)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "degraded", "checks": {"database": ok}},
    )
