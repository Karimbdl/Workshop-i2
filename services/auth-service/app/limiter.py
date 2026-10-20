"""Protection contre la force brute : compteurs d'échecs par compte et par IP.

Arbitrage documenté : si Redis est indisponible, la connexion reste possible
(fail-open) et l'événement est journalisé. On privilégie la disponibilité du
paiement plutôt que de faire de Redis un point de panne unique.
"""

import logging
import os

import redis

from resilience_common.logs import log_event
from resilience_common.secrets import read_secret

logger = logging.getLogger("limiter")

WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))
MAX_FAILS_PER_USER = int(os.getenv("LOGIN_MAX_FAILS_PER_USER", "5"))
MAX_FAILS_PER_IP = int(os.getenv("LOGIN_MAX_FAILS_PER_IP", "20"))


class LoginLimiter:
    def __init__(self) -> None:
        self._redis = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=read_secret("redis_password"),
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=True,
        )

    def is_blocked(self, username: str, ip: str) -> bool:
        try:
            user_fails, ip_fails = self._redis.mget(f"fail:user:{username}", f"fail:ip:{ip}")
        except redis.RedisError as exc:
            log_event(logger, "limiter_unavailable", logging.WARNING, error=str(exc))
            return False
        return int(user_fails or 0) >= MAX_FAILS_PER_USER or int(ip_fails or 0) >= MAX_FAILS_PER_IP

    def register_failure(self, username: str, ip: str) -> None:
        try:
            pipe = self._redis.pipeline()
            for key in (f"fail:user:{username}", f"fail:ip:{ip}"):
                pipe.incr(key)
                pipe.expire(key, WINDOW_SECONDS)
            pipe.execute()
        except redis.RedisError as exc:
            log_event(logger, "limiter_unavailable", logging.WARNING, error=str(exc))

    def reset(self, username: str) -> None:
        try:
            self._redis.delete(f"fail:user:{username}")
        except redis.RedisError:
            pass

    def ping(self) -> bool:
        try:
            return bool(self._redis.ping())
        except redis.RedisError:
            return False
