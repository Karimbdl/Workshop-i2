"""Authentification des appels entre services (jamais exposés par la passerelle)."""

import hmac

from fastapi import Header, HTTPException, status

from .secrets import read_secret


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    expected = read_secret("internal_token")
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Appel interne non autorisé")
