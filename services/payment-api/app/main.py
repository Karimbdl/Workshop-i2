"""payment-api : initiation et suivi des paiements fictifs."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from resilience_common.db import db_is_ready, make_engine, make_session_factory, wait_for_db
from resilience_common.http import setup_http
from resilience_common.internal import require_internal_token
from resilience_common.logs import log_event, setup_logging
from resilience_common.security import Principal, require_roles

from .ledger_client import submit_transfer
from .models import Base, Payment

SERVICE = "payment-api"
MAX_AMOUNT = Decimal(os.getenv("PAYMENT_MAX_AMOUNT", "5000.00"))
RECONCILE_INTERVAL = int(os.getenv("RECONCILE_INTERVAL_SECONDS", "15"))

setup_logging(SERVICE)
logger = logging.getLogger(SERVICE)

engine = make_engine("payment_svc", "db_payment_password", "payment")
SessionLocal = make_session_factory(engine)

PAYMENTS = Counter("payments_total", "Paiements par statut final", ["status"])
PAYMENT_AMOUNT = Counter("payments_amount_cents_total", "Montant cumulé des paiements exécutés (centimes)")
PENDING = Gauge("payments_pending", "Paiements en attente du grand livre")


def apply_outcome(session, payment: Payment) -> None:
    """Envoie le paiement au grand livre et enregistre le résultat."""
    outcome = submit_transfer(payment)
    payment.ledger_attempts += 1
    if outcome.kind == "completed":
        payment.status = "COMPLETED"
        payment.failure_code = payment.failure_reason = None
        PAYMENTS.labels("COMPLETED").inc()
        PAYMENT_AMOUNT.inc(payment.amount_cents)
    elif outcome.kind == "rejected":
        payment.status = "REJECTED"
        payment.failure_code, payment.failure_reason = outcome.code, outcome.detail
        PAYMENTS.labels("REJECTED").inc()
    else:
        payment.failure_code, payment.failure_reason = outcome.code, (outcome.detail or "")[:200]
    session.commit()
    log_event(
        logger,
        "payment_" + payment.status.lower(),
        logging.INFO if outcome.kind != "unavailable" else logging.WARNING,
        payment_id=str(payment.id),
        amount_cents=payment.amount_cents,
        code=payment.failure_code,
        attempts=payment.ledger_attempts,
    )


def reconcile_pending() -> int:
    """Rejoue les paiements restés en attente (grand livre indisponible pendant un incident)."""
    threshold = datetime.now(timezone.utc) - timedelta(seconds=5)
    done = 0
    with SessionLocal() as session:
        pending = session.scalars(
            select(Payment).where(Payment.status == "PENDING", Payment.created_at < threshold).limit(100)
        ).all()
        for payment in pending:
            apply_outcome(session, payment)
            done += payment.status != "PENDING"
        PENDING.set(session.scalar(select(func.count()).where(Payment.status == "PENDING")))
    if pending:
        log_event(logger, "reconcile_run", found=len(pending), resolved=done)
    return done


async def reconcile_loop() -> None:
    while True:
        await asyncio.sleep(RECONCILE_INTERVAL)
        try:
            await run_in_threadpool(reconcile_pending)
        except Exception as exc:
            log_event(logger, "reconcile_failed", logging.WARNING, error=str(exc))


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_db(engine)
    Base.metadata.create_all(engine)
    task = asyncio.create_task(reconcile_loop())
    log_event(logger, "service_started")
    yield
    task.cancel()


app = FastAPI(title="RESILIENCE-ALPHA payment-api", version="1.0.0", lifespan=lifespan)
setup_http(app)


class PaymentIn(BaseModel):
    debit_account_id: uuid.UUID
    credit_iban: str = Field(pattern=r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
    amount: Decimal = Field(gt=0, max_digits=9, decimal_places=2)
    label: str = Field(default="", max_length=140)


def payment_view(p: Payment) -> dict:
    return {
        "id": str(p.id),
        "status": p.status,
        "debit_account_id": str(p.debit_account_id),
        "credit_iban": p.credit_iban,
        "amount": f"{p.amount_cents / 100:.2f}",
        "amount_cents": p.amount_cents,
        "currency": p.currency,
        "label": p.label,
        "failure_code": p.failure_code,
        "failure_reason": p.failure_reason,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


STATUS_CODES = {"COMPLETED": 201, "REJECTED": 422, "PENDING": 202}

client_only = require_roles("client")


@app.post("/payments")
def create_payment(
    body: PaymentIn,
    principal: Principal = Depends(client_only),
    idempotency_key: str = Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9\-]{8,64}$"),
):
    if body.amount > MAX_AMOUNT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Montant maximum : {MAX_AMOUNT} EUR")
    user_id = uuid.UUID(principal.user_id)
    amount_cents = int(body.amount * 100)

    with SessionLocal() as session:
        existing = session.scalar(
            select(Payment).where(Payment.user_id == user_id, Payment.idempotency_key == idempotency_key)
        )
        if existing is None:
            payment = Payment(
                user_id=user_id,
                idempotency_key=idempotency_key,
                debit_account_id=body.debit_account_id,
                credit_iban=body.credit_iban,
                amount_cents=amount_cents,
                label=body.label,
            )
            session.add(payment)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raise HTTPException(status.HTTP_409_CONFLICT, "Paiement déjà en cours avec cette clé")
            log_event(logger, "payment_initiated", payment_id=str(payment.id), amount_cents=amount_cents)
            apply_outcome(session, payment)
        else:
            same = (
                existing.debit_account_id == body.debit_account_id
                and existing.credit_iban == body.credit_iban
                and existing.amount_cents == amount_cents
            )
            if not same:
                raise HTTPException(status.HTTP_409_CONFLICT, "Clé d'idempotence déjà utilisée pour un autre paiement")
            payment = existing
            if payment.status == "PENDING":
                apply_outcome(session, payment)
        # Vue construite avant la fermeture de la session (dates générées par la base).
        view = payment_view(payment)

    return JSONResponse(status_code=STATUS_CODES[payment.status], content=view)


@app.get("/payments")
def list_payments(principal: Principal = Depends(client_only), limit: int = 50):
    limit = max(1, min(limit, 200))
    with SessionLocal() as session:
        payments = session.scalars(
            select(Payment)
            .where(Payment.user_id == uuid.UUID(principal.user_id))
            .order_by(Payment.created_at.desc())
            .limit(limit)
        ).all()
    return [payment_view(p) for p in payments]


@app.get("/payments/{payment_id}")
def get_payment(payment_id: uuid.UUID, principal: Principal = Depends(client_only)):
    with SessionLocal() as session:
        payment = session.get(Payment, payment_id)
    if payment is None or payment.user_id != uuid.UUID(principal.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Paiement introuvable")
    return payment_view(payment)


@app.post("/internal/reconcile", dependencies=[Depends(require_internal_token)])
def reconcile_now():
    """Déclenché par le moteur de remédiation après une reprise."""
    return {"resolved": reconcile_pending()}


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
