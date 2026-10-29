"""Filtered, paginated transaction listing + JSON serialisation."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Customer,
    PaymentMethod,
    ReconciliationStatus,
    Supplier,
    Transaction,
    TransactionType,
)
from app.services.text import normalize_text

MAX_PAGE_SIZE = 200
SORTABLE = {
    "date": Transaction.txn_date,
    "amount": Transaction.amount_iqd,
    "id": Transaction.id,
}


@dataclass
class TxnFilters:
    q: str | None = None
    type: TransactionType | None = None
    payment_method: PaymentMethod | None = None
    status: ReconciliationStatus | None = None
    customer_id: int | None = None
    supplier_id: int | None = None
    category_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_amount: int | None = None
    max_amount: int | None = None


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def apply_filters(stmt, f: TxnFilters):
    if f.q and f.q.strip():
        terms = {f.q.strip(), normalize_text(f.q)}
        conds = []
        for t in terms:
            pat = _like(t)
            conds += [
                Transaction.description.ilike(pat, escape="\\"),
                Transaction.reference.ilike(pat, escape="\\"),
                Customer.name.ilike(pat, escape="\\"),
                Supplier.name.ilike(pat, escape="\\"),
            ]
        stmt = stmt.where(or_(*conds))
    simple = [
        (f.type, Transaction.type),
        (f.payment_method, Transaction.payment_method),
        (f.status, Transaction.reconciliation_status),
        (f.customer_id, Transaction.customer_id),
        (f.supplier_id, Transaction.supplier_id),
        (f.category_id, Transaction.category_id),
    ]
    for value, col in simple:
        if value is not None:
            stmt = stmt.where(col == value)
    if f.date_from:
        stmt = stmt.where(Transaction.txn_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Transaction.txn_date <= f.date_to)
    if f.min_amount is not None:
        stmt = stmt.where(Transaction.amount_iqd >= f.min_amount)
    if f.max_amount is not None:
        stmt = stmt.where(Transaction.amount_iqd <= f.max_amount)
    return stmt


def list_transactions(
    session: Session, f: TxnFilters, *, page: int = 1, page_size: int = 25,
    sort: str = "date", descending: bool = True,
) -> tuple[list[Transaction], int]:
    base = select(Transaction).outerjoin(Customer, Transaction.customer_id == Customer.id).outerjoin(
        Supplier, Transaction.supplier_id == Supplier.id
    )
    base = apply_filters(base, f)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    col = SORTABLE[sort]
    order = [col.desc(), Transaction.id.desc()] if descending else [col.asc(), Transaction.id.asc()]
    rows = session.scalars(
        base.options(selectinload(Transaction.customer), selectinload(Transaction.supplier), selectinload(Transaction.category))
        .order_by(*order)
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return list(rows), total


def serialize(t: Transaction, flags: dict[int, list[dict]] | None = None) -> dict:
    return {
        "id": t.id,
        "date": t.txn_date.isoformat(),
        "type": t.type.value,
        "amount_iqd": t.amount_iqd,
        "description": t.description,
        "reference": t.reference,
        "payment_method": t.payment_method.value,
        "customer": {"id": t.customer.id, "name": t.customer.name} if t.customer else None,
        "supplier": {"id": t.supplier.id, "name": t.supplier.name} if t.supplier else None,
        "category": {"id": t.category.id, "name": t.category.name} if t.category else None,
        "source": t.source.value,
        "import_batch_id": t.import_batch_id,
        "reconciliation_status": t.reconciliation_status.value,
        "flags": (flags or {}).get(t.id, []),
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def flags_by_transaction(flag_list) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for f in flag_list:
        out.setdefault(f.transaction_id, []).append(f.to_dict())
    return out
