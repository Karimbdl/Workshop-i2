"""Test de bout en bout du parcours de paiement, via la passerelle (WAF compris).

Usage : python scripts/smoke_test.py [--base-url http://localhost:8080] [--user alice]
Code de sortie 0 si tout le parcours fonctionne, 1 sinon.
"""

import argparse
import json
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def call(base: str, method: str, path: str, token: str | None = None, body: dict | None = None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}/api{path}", data=data, method=method)
    req.add_header("User-Agent", "resilience-smoke-test/1.0")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw or b"null")
        except json.JSONDecodeError:
            return err.code, raw.decode(errors="replace")[:200]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--user", default="alice")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    users = {u["username"]: u for u in json.loads((ROOT / "secrets" / "seed_users").read_text(encoding="utf-8"))}
    failures = 0

    def check(name: str, ok: bool, detail="") -> None:
        nonlocal failures
        failures += not ok
        print(f"[{'OK' if ok else 'ÉCHEC'}] {name}{' — ' + str(detail) if detail else ''}")

    status, data = call(base, "POST", "/auth/login", body={"username": args.user, "password": users[args.user]["password"]})
    check("connexion", status == 200, status)
    if status != 200:
        return 1
    token = data["access_token"]

    status, accounts = call(base, "GET", "/accounts/me", token)
    check("lecture des comptes", status == 200 and len(accounts) > 0, status)
    if status != 200 or not accounts:
        return 1
    before = accounts[0]["balance_cents"]

    status, beneficiaries = call(base, "GET", "/accounts/beneficiaries", token)
    check("liste des bénéficiaires", status == 200 and len(beneficiaries) > 0, status)
    merchant = next(b for b in beneficiaries if b["iban"].endswith("901"))

    key = uuid.uuid4().hex
    payment = {"debit_account_id": accounts[0]["id"], "credit_iban": merchant["iban"], "amount": "12.34", "label": "Test de bout en bout"}
    status, paid = call(base, "POST", "/payments", token, payment, {"Idempotency-Key": key})
    check("paiement exécuté", status == 201 and paid["status"] == "COMPLETED", f"{status} {paid.get('status') if isinstance(paid, dict) else paid}")

    status, replay = call(base, "POST", "/payments", token, payment, {"Idempotency-Key": key})
    check("rejeu idempotent (pas de double débit)", status == 201 and replay["id"] == paid["id"], status)

    status, accounts = call(base, "GET", "/accounts/me", token)
    after = accounts[0]["balance_cents"]
    check("solde débité une seule fois", before - after == 1234, f"{before} -> {after}")

    status, too_much = call(base, "POST", "/payments", token, {**payment, "amount": "4999.00"}, {"Idempotency-Key": uuid.uuid4().hex})
    check("paiement sans provision refusé", status == 422, f"{status} {too_much.get('failure_code') if isinstance(too_much, dict) else too_much}")

    status, _ = call(base, "GET", "/accounts/me")
    check("accès sans jeton refusé", status == 401, status)

    status, _ = call(base, "GET", "/accounts/me", token + "x")
    check("jeton falsifié refusé", status == 401, status)

    sqli = urllib.parse.quote("' OR 1=1--")
    status, _ = call(base, "GET", f"/accounts/beneficiaries?q={sqli}", token)
    check("injection SQL bloquée par le WAF", status == 403, status)

    for path in ("/internal/integrity", "/payments/../internal/reconcile", "/metrics"):
        status, _ = call(base, "GET", path, token)
        check(f"route interne non exposée ({path})", status in (403, 404), status)

    print(f"\n{'Parcours OK' if failures == 0 else f'{failures} vérification(s) en échec'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
