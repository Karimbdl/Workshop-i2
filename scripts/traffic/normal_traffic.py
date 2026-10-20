"""Générateur de trafic normal pour RESILIENCE-ALPHA.

De faux clients légitimes se connectent, consultent leurs comptes et font de petits paiements,
à un rythme humain et irrégulier. Deux usages :
  - fournir au détecteur ML un « comportement normal » à apprendre (trafic de référence) ;
  - rendre la démonstration vivante.

Tout passe par la passerelle (comme un vrai navigateur). Données entièrement fictives.

Usage :
    python scripts/traffic/normal_traffic.py                        # en continu, intensité moyenne
    python scripts/traffic/normal_traffic.py --duration 600         # pendant 10 min puis s'arrête
    python scripts/traffic/normal_traffic.py --intensity calme      # moins de trafic
    python scripts/traffic/normal_traffic.py --base-url http://192.168.137.1:8080
"""

import argparse
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
UA = "resilience-normal-traffic/1.0"

# Rythme par client : (secondes min, secondes max) entre deux actions.
INTENSITIES = {
    "calme": (6.0, 14.0),
    "moyen": (2.5, 7.0),
    "actif": (1.0, 3.0),
}


def call(base, method, path, token=None, body=None, headers=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}/api{path}", data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"null")
        except (json.JSONDecodeError, ValueError):
            return err.code, None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, None


class Client(threading.Thread):
    """Un client fictif qui vit sa vie : se connecte, regarde ses comptes, paie de temps en temps."""

    def __init__(self, base, user, stop_event, pause_range, stats):
        super().__init__(daemon=True)
        self.base = base
        self.username = user["username"]
        self.password = user["password"]
        self.display = user.get("display_name", user["username"])
        self.stop_event = stop_event
        self.pause_range = pause_range
        self.stats = stats
        self.token = None
        self.accounts = []
        self.beneficiaries = []

    def login(self):
        status, data = call(self.base, "POST", "/auth/login",
                            body={"username": self.username, "password": self.password})
        if status == 200 and data:
            self.token = data["access_token"]
            return True
        self.stats.bump("login_echec")
        return False

    def refresh_context(self):
        status, accounts = call(self.base, "GET", "/accounts/me", self.token)
        if status == 401:
            self.token = None
            return
        if status == 200 and accounts:
            self.accounts = accounts
        status, benef = call(self.base, "GET", "/accounts/beneficiaries", self.token)
        if status == 200 and benef:
            self.beneficiaries = benef

    def make_payment(self):
        usable = [a for a in self.accounts if a.get("status") == "ACTIVE" and int(a["balance_cents"]) > 1000]
        if not usable or not self.beneficiaries:
            return
        account = random.choice(usable)
        target = random.choice(self.beneficiaries)
        amount = f"{random.uniform(0.5, 4.0):.2f}"  # petits montants : le trafic dure longtemps
        labels = ["Café", "Déjeuner", "Abonnement", "Courses", "Remboursement", "Cadeau", "Facture"]
        body = {"debit_account_id": account["id"], "credit_iban": target["iban"],
                "amount": amount, "label": random.choice(labels)}
        status, data = call(self.base, "POST", "/payments", self.token, body,
                           {"Idempotency-Key": uuid.uuid4().hex})
        if status in (201, 202):
            self.stats.bump("paiement_ok")
        elif status == 429:
            self.stats.bump("limite")
            time.sleep(2.0)
        else:
            self.stats.bump("paiement_refuse")

    def run(self):
        while not self.stop_event.is_set():
            if not self.token and not self.login():
                self.stop_event.wait(5)
                continue
            action = random.random()
            if action < 0.55:
                self.refresh_context()
            elif action < 0.9:
                self.make_payment()
            else:
                call(self.base, "GET", "/payments?limit=10", self.token)  # consulte l'historique
            self.stats.bump("actions")
            self.stop_event.wait(random.uniform(*self.pause_range))


class Stats:
    def __init__(self):
        self.counts = {}
        self.lock = threading.Lock()

    def bump(self, key, n=1):
        with self.lock:
            self.counts[key] = self.counts.get(key, 0) + n

    def snapshot(self):
        with self.lock:
            return dict(self.counts)


def main():
    parser = argparse.ArgumentParser(description="Générateur de trafic client normal (données fictives).")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--intensity", choices=list(INTENSITIES), default="moyen")
    parser.add_argument("--duration", type=float, default=0, help="durée en secondes (0 = sans fin, Ctrl+C pour arrêter)")
    parser.add_argument("--users", default="alice,bob,chloe", help="clients fictifs, séparés par des virgules")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    pause_range = INTENSITIES[args.intensity]

    seed = {u["username"]: u for u in json.loads((ROOT / "secrets" / "seed_users").read_text(encoding="utf-8"))}
    chosen = [seed[name] for name in args.users.split(",") if name in seed and seed[name]["role"] == "client"]
    if not chosen:
        print("Aucun client valide trouvé dans secrets/seed_users.", file=sys.stderr)
        return 1

    print(f"Trafic normal — {len(chosen)} clients, intensité « {args.intensity} », cible {base}")
    print("Ctrl+C pour arrêter.\n")

    stop_event = threading.Event()
    stats = Stats()
    clients = [Client(base, u, stop_event, pause_range, stats) for u in chosen]
    for c in clients:
        c.start()

    start = time.monotonic()
    try:
        while not stop_event.is_set():
            time.sleep(10)
            snap = stats.snapshot()
            elapsed = time.monotonic() - start
            print(f"  t+{elapsed:4.0f}s  " + "  ".join(f"{k}={v}" for k, v in sorted(snap.items())))
            if args.duration and elapsed >= args.duration:
                break
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
    finally:
        stop_event.set()

    snap = stats.snapshot()
    print("\nRésumé : " + "  ".join(f"{k}={v}" for k, v in sorted(snap.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
