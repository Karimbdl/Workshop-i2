"""Lecture des secrets.

Les secrets sont toujours lus depuis des fichiers (montés par Docker secrets
aujourd'hui, rendus par Vault Agent ensuite). Le code des services ne change pas
quand la source des secrets change.
"""

import os
from pathlib import Path

SECRETS_DIR = Path(os.getenv("SECRETS_DIR", "/run/secrets"))


def read_secret(name: str, default: str | None = None) -> str:
    path = SECRETS_DIR / name
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    # Repli sur une variable d'environnement : réservé aux tests locaux.
    value = os.getenv(name.upper())
    if value is not None:
        return value
    if default is not None:
        return default
    raise RuntimeError(f"Secret '{name}' introuvable dans {SECRETS_DIR}")
