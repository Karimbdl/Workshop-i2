"""Connexion PostgreSQL : un rôle et un schéma dédiés par service."""

import os
import time

from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from .secrets import read_secret


def make_engine(db_user: str, password_secret: str, schema: str) -> Engine:
    url = URL.create(
        "postgresql+psycopg",
        username=db_user,
        password=read_secret(password_secret),
        host=os.getenv("DB_HOST", "postgres"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "resilience"),
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_timeout=5,
        connect_args={"options": f"-csearch_path={schema}", "connect_timeout": 5},
    )


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def wait_for_db(engine: Engine, attempts: int = 30, delay: float = 2.0) -> None:
    for attempt in range(1, attempts + 1):
        if db_is_ready(engine):
            return
        time.sleep(delay)
    raise RuntimeError("Base de données injoignable au démarrage")


def db_is_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
