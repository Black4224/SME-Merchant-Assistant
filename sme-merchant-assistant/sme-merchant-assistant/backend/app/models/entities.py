"""Relational model. All money columns are integer IQD (no floats, no decimals)."""
from datetime import UTC, date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import (
    CategoryKind,
    PaymentMethod,
    ReconciliationStatus,
    TransactionSource,
    TransactionType,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _enum(enum_cls, length: int = 32):
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[CategoryKind] = mapped_column(_enum(CategoryKind))


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ImportBatch(Base):
    """One CSV upload. `file_sha256` lets us refuse an identical re-upload."""

    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Transaction(Base):
    """Single ledger. Customer payments / supplier payments are rows here too,
    so nothing is ever stored (and therefore counted) twice."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_iqd > 0", name="ck_amount_positive"),
        Index("ix_txn_dedup", "dedup_key", "dedup_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[TransactionType] = mapped_column(_enum(TransactionType), index=True)
    amount_iqd: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(255))
    reference: Mapped[str | None] = mapped_column(String(64))
    payment_method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod))

    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))

    source: Mapped[TransactionSource] = mapped_column(
        _enum(TransactionSource), default=TransactionSource.MANUAL
    )
    reconciliation_status: Mapped[ReconciliationStatus] = mapped_column(
        _enum(ReconciliationStatus), default=ReconciliationStatus.RECONCILED, index=True
    )

    # Duplicate-import detection: hash of the business content + n-th occurrence.
    dedup_key: Mapped[str] = mapped_column(String(64))
    dedup_seq: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    customer: Mapped[Customer | None] = relationship()
    supplier: Mapped[Supplier | None] = relationship()
    category: Mapped[Category | None] = relationship()


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
