"""Comptes de démonstration (fictifs), lus depuis le secret seed_users."""

import json
import logging

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from resilience_common.identity import user_uuid
from resilience_common.logs import log_event
from resilience_common.secrets import read_secret

from .models import User

logger = logging.getLogger("seed")


def seed_users(session: Session, hasher: PasswordHasher) -> None:
    entries = json.loads(read_secret("seed_users"))
    created = 0
    for entry in entries:
        exists = session.scalar(select(User).where(User.username == entry["username"]))
        if exists:
            continue
        session.add(
            User(
                id=user_uuid(entry["username"]),
                username=entry["username"],
                display_name=entry["display_name"],
                password_hash=hasher.hash(entry["password"]),
                role=entry["role"],
                mfa_secret=entry.get("totp_secret"),
            )
        )
        created += 1
    session.commit()
    log_event(logger, "seed_users_done", created=created, total=len(entries))
