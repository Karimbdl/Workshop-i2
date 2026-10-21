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
from resilience_common.identity import user_uuid
from resilience_common.logs import log_event, setup_logging
from resilience_common.security import AUDIENCE, ISSUER, Principal, require_roles

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


# --- Gestion des habilitations (back-office) : réservée aux administrateurs. ---
# Création, listage, activation/désactivation et suppression des comptes de
# supervision (opérateurs et administrateurs). La MFA est obligatoire pour ces
# rôles : à la création, on génère un secret TOTP et on renvoie l'URI à scanner.

admin_only = require_roles("admin")
STAFF_ROLES = {"operator", "admin"}


def user_view(user: User) -> dict:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "mfa_enabled": bool(user.mfa_secret),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


class CreateUserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern=r"^(operator|admin)$")


class UpdateUserIn(BaseModel):
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


@app.get("/auth/users")
def list_users(_: Principal = Depends(admin_only)):
    with SessionLocal() as session:
        users = session.scalars(select(User).order_by(User.created_at)).all()
        return {"users": [user_view(u) for u in users]}


@app.post("/auth/users", status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserIn, principal: Principal = Depends(admin_only)):
    with SessionLocal() as session:
        if session.scalar(select(User).where(User.username == body.username)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Cet identifiant existe déjà")
        secret = pyotp.random_base32()
        user = User(
            id=user_uuid(body.username),
            username=body.username,
            display_name=body.display_name,
            password_hash=hasher.hash(body.password),
            role=body.role,
            mfa_secret=secret,
        )
        session.add(user)
        session.commit()
        view = user_view(user)
    otp_uri = pyotp.TOTP(secret).provisioning_uri(name=body.username, issuer_name="RESILIENCE-ALPHA")
    log_event(logger, "user_created", username=body.username, role=body.role, by=principal.username)
    # Le secret MFA n'est renvoyé qu'une fois, à la création, pour être scanné.
    return {**view, "mfa_secret": secret, "otp_uri": otp_uri}


@app.patch("/auth/users/{username}")
def update_user(username: str, body: UpdateUserIn, principal: Principal = Depends(admin_only)):
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None or user.role not in STAFF_ROLES:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte introuvable")
        if body.is_active is not None:
            if not body.is_active and user.username == principal.username:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Impossible de désactiver son propre compte")
            user.is_active = body.is_active
        if body.password is not None:
            user.password_hash = hasher.hash(body.password)
        session.commit()
        view = user_view(user)
    log_event(logger, "user_updated", username=username, by=principal.username)
    return view


@app.delete("/auth/users/{username}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(username: str, principal: Principal = Depends(admin_only)):
    if username == principal.username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Impossible de supprimer son propre compte")
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None or user.role not in STAFF_ROLES:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte introuvable")
        session.delete(user)
        session.commit()
    log_event(logger, "user_deleted", username=username, by=principal.username)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    checks = {"database": db_is_ready(engine), "redis": limiter.ping()}
    # Redis n'est pas bloquant (fail-open), la base l'est.
    code = status.HTTP_200_OK if checks["database"] else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content={"status": "ready" if code == 200 else "degraded", "checks": checks})
