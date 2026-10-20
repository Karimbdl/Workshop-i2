"""Grand livre en partie double : chaque virement crée deux écritures de somme nulle."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        # Seul le compte système (capital de la banque fictive) peut être négatif.
        CheckConstraint("balance_cents >= 0 OR kind = 'SYSTEM'", name="ck_balance_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # CUSTOMER, MERCHANT, SYSTEM
    label: Mapped[str] = mapped_column(String(128))
    iban: Mapped[str] = mapped_column(String(34), unique=True, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE, FROZEN
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Transfer(Base):
    __tablename__ = "transfers"

    # Identifiant fourni par payment-api : rejouer le même virement ne le duplique pas.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    debit_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    credit_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    reference: Mapped[str] = mapped_column(String(140), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transfer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transfers.id"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)  # négatif = débit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
