"""Règles métier du grand livre : virement atomique et contrôle d'intégrité."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Account, Entry, Transfer


class LedgerError(Exception):
    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass
class TransferResult:
    transfer: Transfer
    created: bool
    debit_balance_cents: int


def execute_transfer(
    session: Session,
    transfer_id: uuid.UUID,
    owner_id: uuid.UUID,
    debit_account_id: uuid.UUID,
    credit_iban: str,
    amount_cents: int,
    currency: str,
    reference: str,
) -> TransferResult:
    existing = session.get(Transfer, transfer_id)
    if existing is not None:
        if existing.debit_account_id != debit_account_id or existing.amount_cents != amount_cents:
            raise LedgerError("transfer_conflict", "Identifiant de virement déjà utilisé", 409)
        debit = session.get(Account, existing.debit_account_id)
        return TransferResult(existing, created=False, debit_balance_cents=debit.balance_cents)

    # On résout l'IBAN en identifiant seul (colonne, pas l'objet ORM) : charger l'objet ici le
    # placerait dans la session, et la relecture verrouillée ci-dessous renverrait cette copie au
    # solde périmé au lieu de la valeur fraîche sous verrou — source d'un « lost update » concurrent.
    credit_id = session.scalar(select(Account.id).where(Account.iban == credit_iban))
    if credit_id is None:
        raise LedgerError("unknown_beneficiary", "IBAN bénéficiaire inconnu", 404)
    if credit_id == debit_account_id:
        raise LedgerError("same_account", "Le compte débité et le compte crédité sont identiques", 422)

    # Verrouillage dans un ordre fixe pour éviter les interblocages entre virements croisés.
    # populate_existing : la relecture verrouillée écrase tout solde déjà en cache dans la session.
    ids = sorted([debit_account_id, credit_id])
    locked = {
        acc.id: acc
        for acc in session.scalars(
            select(Account).where(Account.id.in_(ids)).order_by(Account.id)
            .with_for_update().execution_options(populate_existing=True)
        )
    }
    debit = locked.get(debit_account_id)
    credit = locked.get(credit_id)
    if credit is None:
        raise LedgerError("unknown_beneficiary", "IBAN bénéficiaire inconnu", 404)

    if debit is None or debit.owner_id != owner_id:
        raise LedgerError("unknown_account", "Compte débité introuvable", 404)
    if debit.status != "ACTIVE" or credit.status != "ACTIVE":
        raise LedgerError("account_frozen", "Compte gelé, opération refusée", 423)
    if debit.currency != currency or credit.currency != currency:
        raise LedgerError("currency_mismatch", "Devise non prise en charge pour ce compte", 422)
    if debit.balance_cents < amount_cents:
        raise LedgerError("insufficient_funds", "Solde insuffisant", 422)

    transfer = Transfer(
        id=transfer_id,
        debit_account_id=debit.id,
        credit_account_id=credit.id,
        amount_cents=amount_cents,
        currency=currency,
        reference=reference,
    )
    session.add(transfer)
    # Sans relation ORM déclarée, on force l'insertion du virement avant ses écritures (clé étrangère).
    session.flush()
    session.add_all(
        [
            Entry(transfer_id=transfer_id, account_id=debit.id, amount_cents=-amount_cents),
            Entry(transfer_id=transfer_id, account_id=credit.id, amount_cents=amount_cents),
        ]
    )
    debit.balance_cents -= amount_cents
    credit.balance_cents += amount_cents
    session.flush()
    return TransferResult(transfer, created=True, debit_balance_cents=debit.balance_cents)


def integrity_report(session: Session) -> dict:
    """Vérifie que le grand livre est cohérent.

    Sert à la vérification après remédiation : un service qui répond mais dont
    les soldes sont faux n'est pas considéré comme rétabli.
    """
    anomalies: list[dict] = []

    sums = dict(
        session.execute(select(Entry.account_id, func.sum(Entry.amount_cents)).group_by(Entry.account_id)).all()
    )
    accounts = session.scalars(select(Account)).all()
    for acc in accounts:
        expected = int(sums.get(acc.id, 0) or 0)
        if acc.balance_cents != expected:
            anomalies.append(
                {"check": "balance_matches_entries", "account": acc.iban, "balance": acc.balance_cents, "entries": expected}
            )
        if acc.kind != "SYSTEM" and acc.balance_cents < 0:
            anomalies.append({"check": "non_negative_balance", "account": acc.iban, "balance": acc.balance_cents})

    total = int(session.scalar(select(func.coalesce(func.sum(Entry.amount_cents), 0))))
    if total != 0:
        anomalies.append({"check": "ledger_balanced", "total": total})

    unbalanced = session.execute(
        select(Entry.transfer_id, func.count(), func.sum(Entry.amount_cents))
        .group_by(Entry.transfer_id)
        .having((func.count() != 2) | (func.sum(Entry.amount_cents) != 0))
    ).all()
    for transfer_id, count, amount in unbalanced:
        anomalies.append({"check": "transfer_two_entries", "transfer": str(transfer_id), "entries": count, "sum": int(amount)})

    return {
        "ok": not anomalies,
        "accounts_checked": len(accounts),
        "anomalies": anomalies,
    }
