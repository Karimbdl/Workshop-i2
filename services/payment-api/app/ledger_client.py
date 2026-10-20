"""Appel du grand livre. Le virement est idempotent : on peut le rejouer sans risque."""

import os
import time
from dataclasses import dataclass

import httpx
from prometheus_client import Histogram

from resilience_common.logs import request_id_var
from resilience_common.secrets import read_secret

from .models import Payment

LEDGER_URL = os.getenv("LEDGER_URL", "http://ledger-service:8000")
LEDGER_LATENCY = Histogram(
    "payment_ledger_call_seconds", "Durée des appels au grand livre", ["outcome"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

_client = httpx.Client(base_url=LEDGER_URL, timeout=httpx.Timeout(3.0, connect=1.0))


@dataclass
class LedgerOutcome:
    # completed : virement exécuté ; rejected : refus métier définitif ; unavailable : à rejouer
    kind: str
    code: str | None = None
    detail: str | None = None


def submit_transfer(payment: Payment) -> LedgerOutcome:
    start = time.perf_counter()
    try:
        response = _client.post(
            "/internal/transfers",
            headers={"x-internal-token": read_secret("internal_token"), "x-request-id": request_id_var.get()},
            json={
                "transfer_id": str(payment.id),
                "owner_id": str(payment.user_id),
                "debit_account_id": str(payment.debit_account_id),
                "credit_iban": payment.credit_iban,
                "amount_cents": payment.amount_cents,
                "currency": payment.currency,
                "reference": payment.label,
            },
        )
    except httpx.HTTPError as exc:
        LEDGER_LATENCY.labels("error").observe(time.perf_counter() - start)
        return LedgerOutcome("unavailable", "ledger_unreachable", str(exc)[:200])
    LEDGER_LATENCY.labels(str(response.status_code)).observe(time.perf_counter() - start)

    if response.status_code in (200, 201):
        return LedgerOutcome("completed")
    if response.status_code in (404, 422, 423):
        body = response.json()
        return LedgerOutcome("rejected", body.get("code"), body.get("detail"))
    # 409 (traitement concurrent), 5xx, 401 (secret désynchronisé) : on rejouera.
    return LedgerOutcome("unavailable", f"ledger_http_{response.status_code}", response.text[:200])
