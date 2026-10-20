"""Middleware HTTP commun : identifiant de requête, journal d'accès, métriques."""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.base import BaseHTTPMiddleware

from .logs import log_event, request_id_var

logger = logging.getLogger("access")

QUIET_PATHS = {"/metrics", "/health", "/ready"}


def client_ip(request: Request) -> str:
    # Les services ne sont joignables que par la passerelle, qui renseigne X-Real-IP.
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "-"


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        finally:
            if request.url.path not in QUIET_PATHS:
                log_event(
                    logger,
                    "http_request",
                    method=request.method,
                    path=request.url.path,
                    status=status,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    client_ip=client_ip(request),
                    user_agent=request.headers.get("user-agent", "-"),
                )
            request_id_var.reset(token)


def setup_http(app: FastAPI) -> None:
    app.add_middleware(AccessLogMiddleware)
    Instrumentator(excluded_handlers=list(QUIET_PATHS)).instrument(app).expose(
        app, include_in_schema=False
    )
