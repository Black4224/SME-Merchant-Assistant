"""Deterministic reconciliation / anomaly flags. Nothing here is AI-generated.

Flags (computed on the fly, never silently change stored data):
  possible_duplicate   same date+type+amount+method+reference+description+party as an
                       earlier row (the LATER row is flagged, pointing at the first)
  amount_outlier       sale/expense/purchase > OUTLIER_FACTOR x the median of its own
                       (type, category, payment_method) group (needs MIN_GROUP_SIZE rows)
  future_date          dated after the reference date ("today")
  unreconciled         stored reconciliation_status == unreconciled
  customer_overpayment payment that pushes a customer's balance below zero
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReconciliationStatus, Transaction
from app.models import TransactionType as TT
from app.services.customers import all_customer_balances, customer_ledger
from app.services.metrics import active_filter
from app.services.money import format_iqd
from app.services.periods import DateRange
from app.services.settings_service import get_reference_date
from app.services.text import normalize_text

OUTLIER_FACTOR = 5
MIN_GROUP_SIZE = 4
OUTLIER_TYPES = (TT.SALE, TT.EXPENSE, TT.SUPPLIER_PURCHASE)

SEVERITY = {
    "possible_duplicate": "high",
    "future_date": "high",
    "amount_outlier": "medium",
    "customer_overpayment": "medium",
    "unreconciled": "low",
}


@dataclass(frozen=True)
class AnomalyFlag:
    transaction_id: int
    code: str
    message_ar: str
    related_ids: tuple[int, ...] = ()

    @property
    def severity(self) -> str:
        return SEVERITY[self.code]

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "code": self.code,
            "severity": self.severity,
            "message_ar": self.message_ar,
            "related_ids": list(self.related_ids),
        }


def detect_anomalies(
    session: Session, date_range: DateRange | None = None, reference_date: date | None = None
) -> list[AnomalyFlag]:
    ref = reference_date or get_reference_date(session)
    txns = session.scalars(
        select(Transaction).where(active_filter()).order_by(Transaction.txn_date, Transaction.id)
    ).all()
    flags: list[AnomalyFlag] = []

    # --- possible duplicates -------------------------------------------------
    seen: dict[tuple, int] = {}
    for t in txns:
        key = (
            t.txn_date, t.type, t.amount_iqd, t.payment_method,
            normalize_text(t.reference), normalize_text(t.description),
            t.customer_id, t.supplier_id,
        )
        if key in seen:
            first = seen[key]
            flags.append(AnomalyFlag(t.id, "possible_duplicate",
                                     f"يبدو مكرراً: نفس التاريخ والمبلغ والوصف مثل المعاملة #{first}", (first,)))
        else:
            seen[key] = t.id

    # --- amount outliers -------------------------------------------------------
    groups: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in txns:
        if t.type in OUTLIER_TYPES:
            groups[(t.type, t.category_id, t.payment_method)].append(t)
    for members in groups.values():
        if len(members) < MIN_GROUP_SIZE:
            continue
        med = median(m.amount_iqd for m in members)
        limit = med * OUTLIER_FACTOR
        for m in members:
            if m.amount_iqd > limit:
                flags.append(AnomalyFlag(
                    m.id, "amount_outlier",
                    f"المبلغ {format_iqd(m.amount_iqd)} أكبر بكثير من المعتاد (الوسيط {format_iqd(int(med))})",
                ))

    # --- future dates / unreconciled ----------------------------------------
    for t in txns:
        if t.txn_date > ref:
            flags.append(AnomalyFlag(t.id, "future_date", f"التاريخ {t.txn_date.isoformat()} بعد تاريخ اليوم"))
        if t.reconciliation_status == ReconciliationStatus.UNRECONCILED:
            flags.append(AnomalyFlag(t.id, "unreconciled", "لم تتم مطابقتها بعد"))

    # --- overpayments ----------------------------------------------------------
    far_future = date.max
    for cb in all_customer_balances(session, as_of=far_future):
        for entry in customer_ledger(session, cb.customer_id, as_of=far_future):
            if entry.kind == "payment" and entry.balance_after < 0:
                flags.append(AnomalyFlag(
                    entry.transaction_id, "customer_overpayment",
                    f"الدفعة أكبر من دين الزبون {cb.name} (الرصيد بعدها {format_iqd(entry.balance_after)})",
                ))

    if date_range is not None:
        in_range = {t.id for t in txns if date_range.contains(t.txn_date)}
        flags = [f for f in flags if f.transaction_id in in_range]

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(flags, key=lambda f: (order[f.severity], f.transaction_id, f.code))
