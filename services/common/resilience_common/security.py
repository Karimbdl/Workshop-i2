"""Vérification des jetons JWT émis par auth-service.

Les services récupèrent les clés publiques sur le point JWKS d'auth-service.
Quand la clé de signature est renouvelée (remédiation après vol d'identifiants),
les anciens jetons deviennent invalides partout.
"""

import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ISSUER = "resilience-alpha-auth"
AUDIENCE = "resilience-alpha"
ROLES = ("client", "operator", "admin")


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    url = os.getenv("JWKS_URL", "http://auth-service:8000/.well-known/jwks.json")
    # Cache court : une rotation de clé est prise en compte en moins d'une minute.
    return jwt.PyJWKClient(url, cache_jwk_set=True, lifespan=30, timeout=3)


def decode_token(token: str) -> dict:
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "sub", "role", "jti"]},
    )


_bearer = HTTPBearer(auto_error=False)


def current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise")
    try:
        claims = decode_token(creds.credentials)
    except (jwt.PyJWTError, jwt.PyJWKClientError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton invalide ou expiré")
    if claims["role"] not in ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Rôle inconnu")
    return Principal(claims["sub"], claims.get("username", ""), claims["role"])


def require_roles(*roles: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Droits insuffisants")
        return principal

    return dependency
