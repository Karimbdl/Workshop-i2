"""Comptes fictifs de départ, alimentés depuis le compte système par des virements d'ouverture."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from resilience_common.identity import user_uuid
from resilience_common.logs import log_event

from .models import Account, Entry, Transfer

logger = logging.getLogger("seed")

SYSTEM_IBAN = "FR7630001000010000000000000"
# Compte technique de la sonde : jamais proposé comme bénéficiaire aux clients.
PROBE_IBAN = "FR7630001000010000000000199"

# (propriétaire, type, libellé, IBAN fictif, solde d'ouverture en centimes)
ACCOUNTS = [
    ("alice", "CUSTOMER", "Compte courant Alice Martin", "FR7630001000010000000000101", 250_000),
    ("bob", "CUSTOMER", "Compte courant Bob Durand", "FR7630001000010000000000102", 120_000),
    ("chloe", "CUSTOMER", "Compte courant Chloé Bernard", "FR7630001000010000000000103", 80_000),
    # Compte de la sonde : le moteur de remédiation s'en sert pour prouver qu'un paiement passe.
    ("probe", "CUSTOMER", "Compte sonde de supervision", PROBE_IBAN, 1_000_000),
    (None, "MERCHANT", "Boutique en ligne NovaShop", "FR7630001000010000000000901", 0),
    (None, "MERCHANT", "Électricité VoltaPlus", "FR7630001000010000000000902", 0),
]

OPENING_NAMESPACE = uuid.UUID("0b8f6d1e-55a2-4c1b-9f0e-2d7a3c9b1e44")


def seed_accounts(session: Session) -> None:
    system = session.scalar(select(Account).where(Account.iban == SYSTEM_IBAN))
    if system is None:
        system = Account(kind="SYSTEM", label="Capital Banque Résilience (système)", iban=SYSTEM_IBAN)
        session.add(system)
        session.flush()

    created = 0
    for owner, kind, label, iban, opening in ACCOUNTS:
        if session.scalar(select(Account).where(Account.iban == iban)):
            continue
        account = Account(
            owner_id=user_uuid(owner) if owner else None, kind=kind, label=label, iban=iban, balance_cents=0
        )
        session.add(account)
        session.flush()
        if opening:
            transfer_id = uuid.uuid5(OPENING_NAMESPACE, iban)
            session.add(
                Transfer(
                    id=transfer_id,
                    debit_account_id=system.id,
                    credit_account_id=account.id,
                    amount_cents=opening,
                    currency="EUR",
                    reference="Ouverture de compte",
                )
            )
            session.flush()
            session.add_all(
                [
                    Entry(transfer_id=transfer_id, account_id=system.id, amount_cents=-opening),
                    Entry(transfer_id=transfer_id, account_id=account.id, amount_cents=opening),
                ]
            )
            system.balance_cents -= opening
            account.balance_cents += opening
        created += 1
    session.commit()
    log_event(logger, "seed_accounts_done", created=created)
