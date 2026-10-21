"""Report and dashboard assembly. Pure aggregation over the deterministic services."""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ReconciliationStatus, Transaction
from app.services.anomalies import detect_anomalies
from app.services.cashflow import project_cashflow
from app.services.comparison import compare_periods
from app.services.customers import all_customer_balances, customers_with_debt, total_outstanding
from app.services.metrics import daily_series, summarize_period
from app.services.periods import PERIOD_NAMES, SUNDAY, DateRange, InvalidDateRange, named_period, parse_date
from app.services.settings_service import get_reference_date, get_setting
from app.services.transaction_queries import TxnFilters, flags_by_transaction, list_transactions, serialize

GRANULARITIES = ("daily", "weekly", "monthly")


def resolve_range(session: Session, period: str | None, start: object, end: object, default: str = "this_month") -> tuple[DateRange, str]:
    """Either a named period or an explicit start+end. Returns (range, label)."""
    if (start is None) != (end is None):
        raise InvalidDateRange("يجب تحديد تاريخ البداية والنهاية معاً")
    if start is not None:
        if period:
            raise InvalidDateRange("استخدم إما period أو start/end وليس كليهما")
        return DateRange(parse_date(start), parse_date(end)), "custom"
    name = period or default
    if name not in PERIOD_NAMES:
        raise InvalidDateRange(f"فترة غير معروفة: {name!r}. المتاح: {', '.join(PERIOD_NAMES)}")
    return named_period(name, get_reference_date(session)), name


def _bucket_start(d: date, granularity: str) -> date:
    if granularity == "daily":
        return d
    if granularity == "weekly":
        return d - timedelta(days=(d.weekday() - SUNDAY) % 7)
    return d.replace(day=1)


def bucketed_summary(session: Session, date_range: DateRange, granularity: str) -> list[dict]:
    if granularity not in GRANULARITIES:
        raise InvalidDateRange(f"granularity must be one of {GRANULARITIES}")
    buckets: dict[date, dict] = {}
    for day in daily_series(session, date_range):
        d = date.fromisoformat(day["date"])
        key = _bucket_start(d, granularity)
        b = buckets.setdefault(key, {"start": d, "end": d, "sales": 0, "expenses": 0, "purchases": 0, "cash_in": 0, "cash_out": 0})
        b["end"] = d
        for k in ("sales", "expenses", "purchases", "cash_in", "cash_out"):
            b[k] += day[k]
    out = []
    for b in buckets.values():
        out.append({
            "start": b["start"].isoformat(), "end": b["end"].isoformat(),
            "sales": b["sales"], "expenses": b["expenses"], "purchases": b["purchases"],
            "estimated_profit": b["sales"] - b["purchases"] - b["expenses"],
            "cash_in": b["cash_in"], "cash_out": b["cash_out"], "net_cash_flow": b["cash_in"] - b["cash_out"],
        })
    return out


def reports_summary(session: Session, date_range: DateRange, label: str, granularity: str) -> dict:
    return {
        "period": {"name": label, **date_range.to_dict()},
        "granularity": granularity,
        "totals": summarize_period(session, date_range).to_dict(),
        "series": bucketed_summary(session, date_range, granularity),
        "estimate_note": "الأرباح تقديرية (لا يوجد تتبع للمخزون). التدفق النقدي المتوقع تقدير وليس ضماناً.",
    }


def debts_report(session: Session) -> dict:
    ref = get_reference_date(session)
    owing = customers_with_debt(session)
    return {
        "as_of": ref.isoformat(),
        "credit_terms_days": int(get_setting(session, "credit_terms_days")),
        "total_outstanding": sum(b.outstanding for b in owing),
        "total_overdue": sum(b.overdue_amount for b in owing),
        "customers": [b.to_dict() for b in owing],
    }


def anomalies_report(session: Session, date_range: DateRange | None = None) -> dict:
    flags = detect_anomalies(session, date_range)
    ids = sorted({f.transaction_id for f in flags})
    txns = {}
    if ids:
        for t in session.scalars(select(Transaction).where(Transaction.id.in_(ids))):
            txns[t.id] = t
    by_code: dict[str, int] = {}
    for f in flags:
        by_code[f.code] = by_code.get(f.code, 0) + 1
    return {
        "count": len(flags),
        "by_code": by_code,
        "items": [{**f.to_dict(), "transaction": serialize(txns[f.transaction_id])} for f in flags],
    }


def dashboard_summary(session: Session, date_range: DateRange, label: str) -> dict:
    ref = get_reference_date(session)
    week = named_period("this_week", ref)
    prev_week = DateRange(week.start - timedelta(days=7), week.end - timedelta(days=7))
    flags = detect_anomalies(session)
    owing = customers_with_debt(session)
    unreconciled = session.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.reconciliation_status == ReconciliationStatus.UNRECONCILED)
    ) or 0
    recent, _ = list_transactions(session, TxnFilters(), page=1, page_size=10)
    fl = flags_by_transaction(flags)
    by_code: dict[str, int] = {}
    for f in flags:
        by_code[f.code] = by_code.get(f.code, 0) + 1
    top_flags = [f for f in flags if f.code != "unreconciled"][:10]
    return {
        "business": {
            "name": get_setting(session, "business_name"),
            "currency": get_setting(session, "currency_display"),
            "is_demo_data": get_setting(session, "is_demo_data") == "true",
        },
        "reference_date": ref.isoformat(),
        "period": {"name": label, **date_range.to_dict()},
        "today": summarize_period(session, named_period("today", ref), include_ids=False).to_dict(),
        "period_summary": summarize_period(session, date_range, include_ids=False).to_dict(),
        "outstanding_debts": {
            "total": sum(b.outstanding for b in owing),
            "customers_count": len(owing),
            "overdue_total": sum(b.overdue_amount for b in owing),
        },
        "recent_transactions": [serialize(t, fl) for t in recent],
        "chart": daily_series(session, date_range),
        "weekly_performance": compare_periods(session, week, prev_week).to_dict(),
        "attention": {
            "unreconciled_count": unreconciled,
            "flags_by_code": by_code,
            "top_flags": [f.to_dict() for f in top_flags],
            "overdue_customers": [
                {"customer_id": b.customer_id, "name": b.name, "overdue_amount": b.overdue_amount,
                 "outstanding": b.outstanding, "oldest_unpaid_date": b.oldest_unpaid_date.isoformat() if b.oldest_unpaid_date else None}
                for b in sorted(owing, key=lambda b: -b.overdue_amount) if b.overdue_amount > 0
            ][:5],
        },
    }
