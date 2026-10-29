"""Supplier payables = credit purchases - supplier payments."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaymentMethod, Supplier, Transaction
from app.models import TransactionType as TT
from app.services.metrics import active_filter
from app.services.settings_service import get_reference_date


def supplier_payables(session: Session, as_of: date | None = None) -> list[dict]:
    as_of = as_of or get_reference_date(session)
    names = {s.id: s.name for s in session.scalars(select(Supplier))}
    rows = session.scalars(
        select(Transaction)
        .where(
            Transaction.supplier_id.is_not(None),
            Transaction.txn_date <= as_of,
            active_filter(),
            ((Transaction.type == TT.SUPPLIER_PURCHASE) & (Transaction.payment_method == PaymentMethod.CREDIT))
            | (Transaction.type == TT.SUPPLIER_PAYMENT),
        )
        .order_by(Transaction.txn_date, Transaction.id)
    ).all()
    out = {sid: {"supplier_id": sid, "name": n, "credit_purchases": 0, "payments": 0, "transaction_ids": []} for sid, n in names.items()}
    for t in rows:
        e = out[t.supplier_id]
        e["transaction_ids"].append(t.id)
        if t.type == TT.SUPPLIER_PURCHASE:
            e["credit_purchases"] += t.amount_iqd
        else:
            e["payments"] += t.amount_iqd
    for e in out.values():
        e["outstanding"] = e["credit_purchases"] - e["payments"]
    return sorted(out.values(), key=lambda e: (-e["outstanding"], e["name"]))
