"""Lecture des secrets.

Les secrets sont lus depuis un ou plusieurs dossiers de fichiers. Par défaut
`/run/secrets` (Docker secrets). Un service peut recevoir plusieurs dossiers via
`SECRETS_DIRS` (séparés par « : ») : ils sont essayés dans l'ordre. C'est ce qui
permet d'ajouter Vault (Vault Agent rend les secrets dans un dossier prioritaire)
tout en gardant les Docker secrets comme filet de sécurité :

    SECRETS_DIRS=/vault/secrets:/run/secrets

Le code des services ne change pas quand la source des secrets change.
"""

import os
from pathlib import Path


def _secret_dirs() -> list[Path]:
    dirs = os.getenv("SECRETS_DIRS")
    if dirs:
        # Conteneurs Linux : séparateur « : » (les chemins ne contiennent pas « : »).
        return [Path(d) for d in dirs.split(":") if d]
    return [Path(os.getenv("SECRETS_DIR", "/run/secrets"))]


def read_secret(name: str, default: str | None = None) -> str:
    # On essaie chaque dossier dans l'ordre ; un fichier vide (ex. Vault Agent
    # pas encore prêt) est ignoré pour tomber sur le dossier suivant.
    for directory in _secret_dirs():
        path = directory / name
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    # Repli sur une variable d'environnement : réservé aux tests locaux.
    value = os.getenv(name.upper())
    if value is not None:
        return value
    if default is not None:
        return default
    raise RuntimeError(f"Secret '{name}' introuvable dans {[str(d) for d in _secret_dirs()]}")
