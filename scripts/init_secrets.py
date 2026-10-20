"""Génère les secrets de développement dans ./secrets (jamais versionné).

Usage : python scripts/init_secrets.py [--force]

Ces fichiers servent d'amorçage. En fonctionnement nominal, les secrets des
services sont ensuite servis par HashiCorp Vault.
"""

import argparse
import base64
import json
import secrets
import string
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "secrets"

PASSWORD_ALPHABET = string.ascii_letters + string.digits


def password(length: int = 32) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def rsa_private_key() -> str:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        return key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
    except ImportError:
        out = subprocess.run(
            ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"],
            check=True, capture_output=True, text=True,
        )
        return out.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="régénère les secrets existants")
    args = parser.parse_args()

    SECRETS.mkdir(exist_ok=True)
    demo_password = password(14)
    files = {
        "postgres_password": password,
        "db_auth_password": password,
        "db_ledger_password": password,
        "db_payment_password": password,
        "redis_password": password,
        "internal_token": lambda: secrets.token_urlsafe(48),
        "jwt_private_key": rsa_private_key,
        "grafana_admin_password": lambda: password(20),
        "db_monitor_password": password,
        # Format attendu par redis_exporter : {"adresse": "mot de passe"}.
        "redis_exporter_auth": lambda: json.dumps(
            {"redis://redis:6379": (SECRETS / "redis_password").read_text(encoding="utf-8").strip()}
        ),
        "seed_users": lambda: json.dumps(
            [
                {"username": "alice", "display_name": "Alice Martin", "role": "client", "password": demo_password},
                {"username": "bob", "display_name": "Bob Durand", "role": "client", "password": demo_password},
                {"username": "chloe", "display_name": "Chloé Bernard", "role": "client", "password": demo_password},
                {"username": "probe", "display_name": "Sonde de supervision", "role": "client", "password": password()},
                {"username": "ops", "display_name": "Opérateur SOC", "role": "operator",
                 "password": password(16), "totp_secret": totp_secret()},
                {"username": "admin", "display_name": "Administrateur", "role": "admin",
                 "password": password(20), "totp_secret": totp_secret()},
            ],
            ensure_ascii=False,
            indent=2,
        ),
    }

    created = []
    for name, factory in files.items():
        path = SECRETS / name
        if path.exists() and not args.force:
            continue
        path.write_text(factory(), encoding="utf-8")
        created.append(name)

    print(f"Secrets créés : {', '.join(created) if created else 'aucun (déjà présents)'}")
    users = json.loads((SECRETS / "seed_users").read_text(encoding="utf-8"))
    print("\nComptes de démonstration (fictifs) :")
    for u in users:
        mfa = f"  TOTP={u['totp_secret']}" if u.get("totp_secret") else ""
        print(f"  {u['role']:<8} {u['username']:<6} mot de passe={u['password']}{mfa}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
