"""Deterministic period metrics. All amounts are integer IQD.

Definitions (docs/business-rules.md):
  sales_total          every SALE (cash, digital, bank AND credit) = revenue booked
  sales_collected      sales paid at the time of sale (cash/digital/bank)
  sales_credit         sales on account - NOT money received yet
  customer_payments    money received against earlier credit sales - NEVER counted as sales
  expenses_total       operating expenses (rent, power, salaries, ...)
  purchases_total      stock bought from suppliers (cash or on credit)
  supplier_payments    cash paid to settle supplier credit - NOT a new cost
  cash_in              sales_collected + customer_payments
  cash_out             expenses + non-credit purchases + supplier_payments
  estimated_profit     sales_total - purchases_total - expenses_total   (ESTIMATE:
                       stock on hand is unknown, so purchases stand in for COGS)
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PaymentMethod as PM
from app.models import ReconciliationStatus, Transaction
from app.models import TransactionType as TT
from app.services.periods import DateRange

PROFIT_BASIS = "purchases_basis_estimate"
PROFIT_NOTE_AR = (
    "الربح تقديري: المبيعات − مشتريات البضاعة − المصاريف التشغيلية. "
    "لا يوجد تتبع للمخزون أو لكلفة البضاعة المباعة الفعلية."
)
COLLECTED_AT_SALE = (PM.CASH, PM.DIGITAL, PM.BANK)


def active_filter():
    """Excluded (duplicate/void) rows never take part in any figure."""
    return Transaction.reconciliation_status != ReconciliationStatus.EXCLUDED


@dataclass(frozen=True)
class PeriodSummary:
    date_range: DateRange
    sales_total: int
    sales_collected: int
    sales_credit: int
    customer_payments: int
    expenses_total: int
    purchases_total: int
    purchases_credit: int
    supplier_payments: int
    cash_in: int
    cash_out: int
    net_cash_flow: int
    estimated_profit: int
    transaction_counts: dict[str, int] = field(default_factory=dict)
    transaction_ids: dict[str, list[int]] = field(default_factory=dict)
    excluded_count: int = 0
    profit_basis: str = PROFIT_BASIS
    profit_note: str = PROFIT_NOTE_AR

    def to_dict(self) -> dict:
        return {
            "date_range": self.date_range.to_dict(),
            "sales_total": self.sales_total,
            "sales_collected": self.sales_collected,
            "sales_credit": self.sales_credit,
            "customer_payments": self.customer_payments,
            "expenses_total": self.expenses_total,
            "purchases_total": self.purchases_total,
            "purchases_credit": self.purchases_credit,
            "supplier_payments": self.supplier_payments,
            "cash_in": self.cash_in,
            "cash_out": self.cash_out,
            "net_cash_flow": self.net_cash_flow,
            "estimated_profit": self.estimated_profit,
            "profit_basis": self.profit_basis,
            "profit_note": self.profit_note,
            "transaction_counts": self.transaction_counts,
            "transaction_ids": self.transaction_ids,
            "excluded_count": self.excluded_count,
        }


def summarize_period(
    session: Session, date_range: DateRange, *, include_ids: bool = True
) -> PeriodSummary:
    rows = session.execute(
        select(Transaction.id, Transaction.type, Transaction.payment_method, Transaction.amount_iqd)
        .where(Transaction.txn_date.between(date_range.start, date_range.end), active_filter())
        .order_by(Transaction.txn_date, Transaction.id)
    ).all()

    sales_collected = sales_credit = payments = expenses = 0
    purchases = purchases_credit = supplier_payments = 0
    ids: dict[str, list[int]] = defaultdict(list)

    for txn_id, ttype, method, amount in rows:
        ids[ttype.value].append(txn_id)
        if ttype == TT.SALE:
            if method == PM.CREDIT:
                sales_credit += amount
            else:
                sales_collected += amount
        elif ttype == TT.CUSTOMER_PAYMENT:
            payments += amount
        elif ttype == TT.EXPENSE:
            expenses += amount
        elif ttype == TT.SUPPLIER_PURCHASE:
            purchases += amount
            if method == PM.CREDIT:
                purchases_credit += amount
        elif ttype == TT.SUPPLIER_PAYMENT:
            supplier_payments += amount

    sales_total = sales_collected + sales_credit
    cash_in = sales_collected + payments
    cash_out = expenses + (purchases - purchases_credit) + supplier_payments

    excluded = session.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.txn_date.between(date_range.start, date_range.end),
            Transaction.reconciliation_status == ReconciliationStatus.EXCLUDED,
        )
    )
    return PeriodSummary(
        date_range=date_range,
        sales_total=sales_total,
        sales_collected=sales_collected,
        sales_credit=sales_credit,
        customer_payments=payments,
        expenses_total=expenses,
        purchases_total=purchases,
        purchases_credit=purchases_credit,
        supplier_payments=supplier_payments,
        cash_in=cash_in,
        cash_out=cash_out,
        net_cash_flow=cash_in - cash_out,
        estimated_profit=sales_total - purchases - expenses,
        transaction_counts={k: len(v) for k, v in ids.items()},
        transaction_ids=dict(ids) if include_ids else {},
        excluded_count=excluded or 0,
    )


def daily_series(session: Session, date_range: DateRange) -> list[dict]:
    """One entry per calendar day (zeros included) - feeds the dashboard chart."""
    rows = session.execute(
        select(Transaction.txn_date, Transaction.type, Transaction.payment_method, Transaction.amount_iqd)
        .where(Transaction.txn_date.between(date_range.start, date_range.end), active_filter())
    ).all()
    days: dict[date, dict[str, int]] = {
        d: {"sales": 0, "expenses": 0, "purchases": 0, "cash_in": 0, "cash_out": 0}
        for d in date_range.each_day()
    }
    for d, ttype, method, amount in rows:
        bucket = days[d]
        if ttype == TT.SALE:
            bucket["sales"] += amount
            if method != PM.CREDIT:
                bucket["cash_in"] += amount
        elif ttype == TT.CUSTOMER_PAYMENT:
            bucket["cash_in"] += amount
        elif ttype == TT.EXPENSE:
            bucket["expenses"] += amount
            bucket["cash_out"] += amount
        elif ttype == TT.SUPPLIER_PURCHASE:
            bucket["purchases"] += amount
            if method != PM.CREDIT:
                bucket["cash_out"] += amount
        elif ttype == TT.SUPPLIER_PAYMENT:
            bucket["cash_out"] += amount
    return [{"date": d.isoformat(), **vals} for d, vals in days.items()]
