"""auth-service : authentification, émission des jetons JWT, MFA pour les opérateurs."""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import Counter
from pydantic import BaseModel, Field
from sqlalchemy import select

from resilience_common.db import db_is_ready, make_engine, make_session_factory, wait_for_db
from resilience_common.http import client_ip, setup_http
from resilience_common.logs import log_event, setup_logging
from resilience_common.security import AUDIENCE, ISSUER

from .keys import key_store
from .limiter import LoginLimiter
from .models import Base, User
from .seed import seed_users

SERVICE = "auth-service"
ACCESS_TTL = timedelta(minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "15")))
MFA_ROLES = {"operator", "admin"}

setup_logging(SERVICE)
logger = logging.getLogger(SERVICE)

engine = make_engine("auth_svc", "db_auth_password", "auth")
SessionLocal = make_session_factory(engine)
hasher = PasswordHasher()
# Hash factice : on vérifie quand même un mot de passe si le compte n'existe pas,
# pour que le temps de réponse ne révèle pas quels comptes existent.
DUMMY_HASH = hasher.hash(uuid.uuid4().hex)
limiter = LoginLimiter()

LOGIN_ATTEMPTS = Counter("auth_login_attempts_total", "Tentatives de connexion", ["result"])


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_db(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_users(session, hasher)
    key_store.current()
    log_event(logger, "service_started")
    yield


app = FastAPI(title="RESILIENCE-ALPHA auth-service", version="1.0.0", lifespan=lifespan)
setup_http(app)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    otp: str | None = Field(default=None, pattern=r"^\d{6}$")


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    display_name: str


def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    key = key_store.current()
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": now,
        "nbf": now,
        "exp": now + ACCESS_TTL,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, key.private_pem, algorithm="RS256", headers={"kid": key.kid})


def login_failed(username: str, ip: str, reason: str) -> HTTPException:
    limiter.register_failure(username, ip)
    LOGIN_ATTEMPTS.labels("failure").inc()
    log_event(logger, "login_failed", logging.WARNING, username=username, client_ip=ip, reason=reason)
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides")


@app.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request):
    ip = client_ip(request)
    if limiter.is_blocked(body.username, ip):
        LOGIN_ATTEMPTS.labels("blocked").inc()
        log_event(logger, "login_blocked", logging.WARNING, username=body.username, client_ip=ip)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessayez plus tard")

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == body.username))
        try:
            hasher.verify(user.password_hash if user else DUMMY_HASH, body.password)
        except VerifyMismatchError:
            raise login_failed(body.username, ip, "unknown_user" if user is None else "bad_password")
        if user is None or not user.is_active:
            raise login_failed(body.username, ip, "inactive")

        if user.role in MFA_ROLES and user.mfa_secret:
            if body.otp is None:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Code MFA requis", "mfa_required": True},
                )
            if not pyotp.TOTP(user.mfa_secret).verify(body.otp, valid_window=1):
                raise login_failed(body.username, ip, "bad_otp")

        user.last_login_at = datetime.now(timezone.utc)
        session.commit()

    limiter.reset(body.username)
    LOGIN_ATTEMPTS.labels("success").inc()
    log_event(logger, "login_success", username=user.username, role=user.role, client_ip=ip)
    return TokenOut(
        access_token=issue_token(user),
        expires_in=int(ACCESS_TTL.total_seconds()),
        role=user.role,
        display_name=user.display_name,
    )


_bearer = HTTPBearer(auto_error=False)


@app.get("/auth/me")
def me(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise")
    key = key_store.current()
    public_key = jwt.PyJWK(key.jwk).key
    try:
        claims = jwt.decode(
            creds.credentials, public_key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER
        )
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton invalide ou expiré")
    return {"user_id": claims["sub"], "username": claims["username"], "role": claims["role"]}


@app.get("/.well-known/jwks.json")
def jwks():
    return {"keys": [key_store.current().jwk]}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    checks = {"database": db_is_ready(engine), "redis": limiter.ping()}
    # Redis n'est pas bloquant (fail-open), la base l'est.
    code = status.HTTP_200_OK if checks["database"] else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content={"status": "ready" if code == 200 else "degraded", "checks": checks})
