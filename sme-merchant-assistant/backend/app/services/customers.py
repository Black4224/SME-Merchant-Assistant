"""Customer debts. Debt = credit sales - customer payments (excluded rows ignored).

Payments are not tied to invoices, so they are applied to the OLDEST unpaid credit
sale first (FIFO). That gives a deterministic definition of "overdue":
an unpaid remainder of a credit sale older than `credit_terms_days`.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, PaymentMethod, Transaction
from app.models import TransactionType as TT
from app.services.metrics import active_filter
from app.services.periods import DateRange
from app.services.settings_service import get_credit_terms_days, get_reference_date


@dataclass(frozen=True)
class LedgerEntry:
    transaction_id: int
    date: date
    kind: str  # "credit_sale" | "payment"
    amount: int
    description: str
    balance_after: int
    payment_method: str


@dataclass(frozen=True)
class OpenInvoice:
    transaction_id: int
    date: date
    original_amount: int
    remaining: int
    age_days: int
    overdue: bool


@dataclass
class CustomerBalance:
    customer_id: int
    name: str
    credit_sales_total: int = 0
    payments_total: int = 0
    outstanding: int = 0  # negative => customer has overpaid (credit in their favour)
    overdue_amount: int = 0
    last_payment_date: date | None = None
    oldest_unpaid_date: date | None = None
    open_invoices: list[OpenInvoice] = field(default_factory=list)
    credit_sale_ids: list[int] = field(default_factory=list)
    payment_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "customer_id": self.customer_id,
            "name": self.name,
            "credit_sales_total": self.credit_sales_total,
            "payments_total": self.payments_total,
            "outstanding": self.outstanding,
            "overdue_amount": self.overdue_amount,
            "last_payment_date": self.last_payment_date.isoformat() if self.last_payment_date else None,
            "oldest_unpaid_date": self.oldest_unpaid_date.isoformat() if self.oldest_unpaid_date else None,
            "open_invoices": [
                {
                    "transaction_id": i.transaction_id,
                    "date": i.date.isoformat(),
                    "original_amount": i.original_amount,
                    "remaining": i.remaining,
                    "age_days": i.age_days,
                    "overdue": i.overdue,
                }
                for i in self.open_invoices
            ],
            "credit_sale_ids": self.credit_sale_ids,
            "payment_ids": self.payment_ids,
        }


def _debt_rows(session: Session, as_of: date, customer_id: int | None = None):
    q = (
        select(Transaction)
        .where(
            Transaction.customer_id.is_not(None),
            Transaction.txn_date <= as_of,
            active_filter(),
            (
                (Transaction.type == TT.SALE) & (Transaction.payment_method == PaymentMethod.CREDIT)
            )
            | (Transaction.type == TT.CUSTOMER_PAYMENT),
        )
        .order_by(Transaction.txn_date, Transaction.id)
    )
    if customer_id is not None:
        q = q.where(Transaction.customer_id == customer_id)
    return session.scalars(q).all()


def customer_ledger(session: Session, customer_id: int, as_of: date | None = None) -> list[LedgerEntry]:
    """Chronological debt history with running balance."""
    as_of = as_of or get_reference_date(session)
    balance = 0
    out: list[LedgerEntry] = []
    for t in _debt_rows(session, as_of, customer_id):
        if t.type == TT.SALE:
            balance += t.amount_iqd
            kind = "credit_sale"
        else:
            balance -= t.amount_iqd
            kind = "payment"
        out.append(
            LedgerEntry(t.id, t.txn_date, kind, t.amount_iqd, t.description, balance, t.payment_method.value)
        )
    return out


def all_customer_balances(
    session: Session, as_of: date | None = None, credit_terms_days: int | None = None
) -> list[CustomerBalance]:
    as_of = as_of or get_reference_date(session)
    terms = credit_terms_days if credit_terms_days is not None else get_credit_terms_days(session)
    names = {c.id: c.name for c in session.scalars(select(Customer))}
    by_customer: dict[int, list[Transaction]] = {}
    for t in _debt_rows(session, as_of):
        by_customer.setdefault(t.customer_id, []).append(t)

    result: list[CustomerBalance] = []
    for cid, name in names.items():
        bal = CustomerBalance(customer_id=cid, name=name)
        invoices: list[list] = []  # [txn, remaining]
        for t in by_customer.get(cid, []):
            if t.type == TT.SALE:
                bal.credit_sales_total += t.amount_iqd
                bal.credit_sale_ids.append(t.id)
                invoices.append([t, t.amount_iqd])
            else:
                bal.payments_total += t.amount_iqd
                bal.payment_ids.append(t.id)
                bal.last_payment_date = t.txn_date
                left = t.amount_iqd
                for inv in invoices:  # FIFO
                    if left == 0:
                        break
                    take = min(inv[1], left)
                    inv[1] -= take
                    left -= take
        bal.outstanding = bal.credit_sales_total - bal.payments_total
        for t, remaining in invoices:
            if remaining > 0:
                age = (as_of - t.txn_date).days
                overdue = age > terms
                bal.open_invoices.append(OpenInvoice(t.id, t.txn_date, t.amount_iqd, remaining, age, overdue))
                if overdue:
                    bal.overdue_amount += remaining
        if bal.open_invoices:
            bal.oldest_unpaid_date = bal.open_invoices[0].date
        result.append(bal)
    return result


def customers_with_debt(session: Session, as_of: date | None = None) -> list[CustomerBalance]:
    """Customers who currently owe money, largest debt first (ties: name)."""
    owing = [b for b in all_customer_balances(session, as_of) if b.outstanding > 0]
    return sorted(owing, key=lambda b: (-b.outstanding, b.name))


def total_outstanding(session: Session, as_of: date | None = None) -> int:
    return sum(b.outstanding for b in all_customer_balances(session, as_of) if b.outstanding > 0)


def customer_payments_in_range(
    session: Session, date_range: DateRange, customer_id: int | None = None
) -> list[Transaction]:
    q = (
        select(Transaction)
        .where(
            Transaction.type == TT.CUSTOMER_PAYMENT,
            Transaction.txn_date.between(date_range.start, date_range.end),
            active_filter(),
        )
        .order_by(Transaction.txn_date, Transaction.id)
    )
    if customer_id is not None:
        q = q.where(Transaction.customer_id == customer_id)
    return list(session.scalars(q))


def top_customers_by_sales(session: Session, date_range: DateRange, limit: int = 5) -> list[dict]:
    """Customers ranked by revenue (all payment methods) - 'who buys most from me'."""
    rows = session.execute(
        select(Transaction.customer_id, Transaction.id, Transaction.amount_iqd).where(
            Transaction.type == TT.SALE,
            Transaction.customer_id.is_not(None),
            Transaction.txn_date.between(date_range.start, date_range.end),
            active_filter(),
        )
    ).all()
    totals: dict[int, dict] = {}
    for cid, tid, amt in rows:
        e = totals.setdefault(cid, {"customer_id": cid, "total": 0, "transaction_ids": []})
        e["total"] += amt
        e["transaction_ids"].append(tid)
    names = {c.id: c.name for c in session.scalars(select(Customer))}
    ranked = sorted(totals.values(), key=lambda e: (-e["total"], names[e["customer_id"]]))
    return [{**e, "name": names[e["customer_id"]]} for e in ranked[:limit]]
