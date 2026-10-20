"""Identifiants déterministes des utilisateurs de démonstration.

auth-service et ledger-service créent leurs données de départ chacun de leur
côté : un UUID dérivé du nom d'utilisateur leur permet de s'accorder sans
partager de base.
"""

import uuid

NAMESPACE = uuid.UUID("6f1c2a52-3c1e-4f43-9a51-7e2b8d0c4a10")


def user_uuid(username: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, username)
