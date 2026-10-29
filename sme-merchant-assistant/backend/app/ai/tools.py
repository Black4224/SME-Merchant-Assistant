"""Allowlisted, read-only, validated tools. The ONLY way the assistant touches financial data.

Every handler: validated args -> deterministic services -> ToolResult (figures + evidence ids).
No SQL, shell or free-form access is exposed; unknown tools and unknown arguments are rejected.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.tool_result import MAX_ID_LIST, Figure, ToolResult
from app.models import Category, Customer, Transaction, TransactionType
from app.services import reports
from app.services.anomalies import detect_anomalies
from app.services.cashflow import project_cashflow
from app.services.comparison import compare_periods as _compare_periods
from app.services.customers import all_customer_balances, customer_payments_in_range, top_customers_by_sales
from app.services.metrics import active_filter, summarize_period
from app.services.money import format_iqd
from app.services.periods import PERIOD_NAMES, DateRange, InvalidDateRange, named_period, parse_date
from app.services.settings_service import get_reference_date
from app.services.names import name_matches
from app.services.text import normalize_text
from app.services.transaction_queries import TxnFilters, list_transactions, serialize

PeriodName = Literal[
    "today", "yesterday", "this_week", "last_week", "this_month", "last_month",
    "last_month_same_span", "last_7_days", "last_30_days",
]
TYPE_AR = {"sale": "بيع", "customer_payment": "تسديد زبون", "expense": "مصروف",
           "supplier_purchase": "شراء بضاعة", "supplier_payment": "تسديد مورد"}
METHOD_AR = {"cash": "نقد", "digital": "محفظة إلكترونية", "bank": "بنك/بطاقة", "credit": "آجل"}
FLAG_AR = {"possible_duplicate": "احتمال تكرار", "future_date": "تاريخ مستقبلي", "amount_outlier": "مبلغ غير معتاد",
           "customer_overpayment": "دفعة زائدة", "unreconciled": "غير مطابقة"}


class ToolArgError(ValueError):
    """Bad or insufficient arguments. The message goes back to the model so it can fix the call
    or ask the user a clarification question."""


# ----------------------------------------------------------------------------- args
class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PeriodArgs(_Args):
    period: PeriodName | None = Field(None, description="Named period relative to today.")
    start_date: str | None = Field(None, description="Custom range start, YYYY-MM-DD (use with end_date).")
    end_date: str | None = Field(None, description="Custom range end, YYYY-MM-DD (use with start_date).")

    def resolve(self, session: Session, *, required: bool = True) -> tuple[DateRange, str] | None:
        if self.period is None and self.start_date is None and self.end_date is None:
            if required:
                raise ToolArgError("الفترة غير محددة. اسأل المستخدم عن الفترة المقصودة (اليوم؟ هذا الأسبوع؟ هذا الشهر؟).")
            return None
        return reports.resolve_range(session, self.period, self.start_date, self.end_date)


class NoArgs(_Args):
    pass


class DebtsArgs(_Args):
    customer_name: str | None = Field(None, max_length=120, description="Filter by customer name (partial match ok).")
    only_overdue: bool = Field(False, description="Only customers with overdue debt.")
    limit: int = Field(10, ge=1, le=50, description="Max customers listed (totals always cover all matches).")


class PaymentHistoryArgs(PeriodArgs):
    customer_name: str = Field(..., min_length=1, max_length=120)


class RecentArgs(_Args):
    limit: int = Field(10, ge=1, le=20)
    type: TransactionType | None = None


class UnreconciledArgs(PeriodArgs):
    pass


class CompareArgs(_Args):
    current_period: PeriodName | None = None
    current_start: str | None = None
    current_end: str | None = None
    previous_period: PeriodName | None = None
    previous_start: str | None = None
    previous_end: str | None = None


class CashflowArgs(_Args):
    horizon_days: int = Field(30, ge=1, le=90)


class TopCustomersArgs(PeriodArgs):
    limit: int = Field(5, ge=1, le=20)


# ----------------------------------------------------------------------------- helpers
def _fig(key: str, label: str, value: int, money: bool = True) -> Figure:
    return Figure(key, label, value, format_iqd(value) if money else f"{value:,}")


def _txns_by_ids(session: Session, ids: list[int], limit: int = 25) -> list[dict]:
    if not ids:
        return []
    rows = session.scalars(
        select(Transaction).where(Transaction.id.in_(ids[-limit * 4 :])).order_by(Transaction.txn_date.desc(), Transaction.id.desc()).limit(limit)
    ).all()
    return [serialize(t) for t in rows]


def _cap(ids: list[int]) -> tuple[list[int], bool]:
    return (ids[:MAX_ID_LIST], len(ids) > MAX_ID_LIST)


def _find_customers(session: Session, name: str) -> list[Customer]:
    needle = normalize_text(name)
    customers = list(session.scalars(select(Customer)))
    exact = [c for c in customers if normalize_text(c.name) == needle]
    return exact or [c for c in customers if name_matches(name, c.name)]


# ----------------------------------------------------------------------------- handlers
def sales_summary(session: Session, a: PeriodArgs) -> ToolResult:
    rng, _ = a.resolve(session)
    m = summarize_period(session, rng)
    ids, trunc = _cap(m.transaction_ids.get("sale", []))
    n = m.transaction_counts.get("sale", 0)
    return ToolResult(
        tool="get_sales_summary", arguments=a.model_dump(exclude_none=True), title_ar="ملخص المبيعات",
        basis_ar="إجمالي المبيعات = كل فواتير البيع (نقد + محفظة/بنك + آجل). دفعات الزبائن على الديون القديمة ليست مبيعات جديدة.",
        date_range=rng.to_dict(),
        figures=[_fig("sales_total", "إجمالي المبيعات", m.sales_total), _fig("sales_collected", "مبيعات مقبوضة وقت البيع", m.sales_collected),
                 _fig("sales_credit", "مبيعات آجلة (لم تُقبض بعد)", m.sales_credit), _fig("sales_count", "عدد فواتير البيع", n, money=False)],
        id_groups={"sale": ids}, transactions=_txns_by_ids(session, ids), ids_truncated=trunc, has_data=n > 0,
    )


def expenses_summary(session: Session, a: PeriodArgs) -> ToolResult:
    rng, _ = a.resolve(session)
    m = summarize_period(session, rng)
    exp_ids = m.transaction_ids.get("expense", [])
    by_cat: dict[str, dict] = {}
    if exp_ids:
        cats = {c.id: c.name for c in session.scalars(select(Category))}
        for t in session.scalars(select(Transaction).where(Transaction.id.in_(exp_ids))):
            e = by_cat.setdefault(cats.get(t.category_id, "بدون تصنيف"), {"total": 0, "count": 0})
            e["total"] += t.amount_iqd
            e["count"] += 1
    rows = [{"category": k, "total": format_iqd(v["total"]), "count": v["count"]} for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]["total"])]
    groups = {"expense": exp_ids, "supplier_purchase": m.transaction_ids.get("supplier_purchase", []),
              "supplier_payment": m.transaction_ids.get("supplier_payment", [])}
    flat = [i for g in groups.values() for i in g]
    return ToolResult(
        tool="get_expenses_summary", arguments=a.model_dump(exclude_none=True), title_ar="ملخص المصاريف",
        basis_ar="المصاريف التشغيلية (إيجار، مولدة، رواتب...) منفصلة عن مشتريات البضاعة. تسديد المورد يسدّد شراءً آجلاً ولا يُعدّ كلفة جديدة.",
        date_range=rng.to_dict(),
        figures=[_fig("expenses_total", "المصاريف التشغيلية", m.expenses_total), _fig("purchases_total", "مشتريات البضاعة", m.purchases_total),
                 _fig("purchases_credit", "منها مشتريات آجلة", m.purchases_credit), _fig("supplier_payments", "المدفوع للموردين", m.supplier_payments)],
        table_columns=[{"key": "category", "label_ar": "التصنيف"}, {"key": "total", "label_ar": "المبلغ"}, {"key": "count", "label_ar": "العدد"}],
        table_rows=rows, id_groups={k: v[:MAX_ID_LIST] for k, v in groups.items()}, transactions=_txns_by_ids(session, flat),
        ids_truncated=any(len(v) > MAX_ID_LIST for v in groups.values()), has_data=bool(flat),
    )


def profit_summary(session: Session, a: PeriodArgs) -> ToolResult:
    rng, _ = a.resolve(session)
    m = summarize_period(session, rng)
    groups = {k: m.transaction_ids.get(k, [])[:MAX_ID_LIST] for k in ("sale", "supplier_purchase", "expense")}
    flat = [i for g in groups.values() for i in g]
    return ToolResult(
        tool="get_profit_summary", arguments=a.model_dump(exclude_none=True), title_ar="الربح التقديري",
        basis_ar="الربح التقديري = المبيعات − مشتريات البضاعة − المصاريف التشغيلية. لا يوجد تتبع للمخزون، لذا الرقم تقدير وليس ربحاً محاسبياً نهائياً.",
        date_range=rng.to_dict(),
        figures=[_fig("sales_total", "المبيعات", m.sales_total), _fig("purchases_total", "مشتريات البضاعة", m.purchases_total),
                 _fig("expenses_total", "المصاريف التشغيلية", m.expenses_total), _fig("estimated_profit", "الربح التقديري", m.estimated_profit),
                 _fig("net_cash_flow", "صافي النقد (مقبوض − مدفوع)", m.net_cash_flow)],
        id_groups=groups, transactions=_txns_by_ids(session, flat), is_estimate=True, has_data=bool(flat),
        warnings=["الربح تقديري. صافي النقد يختلف عن الربح لأن المبيعات الآجلة لم تُقبض والمشتريات الآجلة لم تُدفع."],
    )


def customer_debts(session: Session, a: DebtsArgs) -> ToolResult:
    balances = [b for b in all_customer_balances(session) if b.outstanding > 0]
    warnings: list[str] = []
    if a.customer_name:
        balances = [b for b in balances if name_matches(a.customer_name, b.name)]
    if a.only_overdue:
        balances = [b for b in balances if b.overdue_amount > 0]
    balances.sort(key=lambda b: (-b.outstanding, b.name))
    shown = balances[: a.limit]
    if len(balances) > len(shown):
        warnings.append(f"تم عرض أكبر {len(shown)} من أصل {len(balances)} زبون؛ الإجماليات تشمل الجميع.")
    open_ids = [i.transaction_id for b in balances for i in b.open_invoices]
    ids, trunc = _cap(open_ids)
    rows = [{"customer": b.name, "outstanding": format_iqd(b.outstanding), "overdue": format_iqd(b.overdue_amount),
             "oldest_unpaid": b.oldest_unpaid_date.isoformat() if b.oldest_unpaid_date else "", "open_invoices": len(b.open_invoices)}
            for b in shown]
    return ToolResult(
        tool="get_customer_debts", arguments=a.model_dump(exclude_none=True), title_ar="ديون الزبائن",
        basis_ar="الدين = مبيعات آجلة − دفعات الزبون. الدفعات تُسدَّد من أقدم فاتورة أولاً، والمتأخر = متبقٍّ من فاتورة آجلة عمرها أكثر من مدة الائتمان (30 يوماً افتراضياً).",
        date_range={"start": get_reference_date(session).isoformat(), "end": get_reference_date(session).isoformat(), "days": 1},
        figures=[_fig("customers_count", "عدد الزبائن المدينين", len(balances), money=False),
                 _fig("total_outstanding", "إجمالي الديون", sum(b.outstanding for b in balances)),
                 _fig("total_overdue", "منها متأخر", sum(b.overdue_amount for b in balances))],
        table_columns=[{"key": "customer", "label_ar": "الزبون"}, {"key": "outstanding", "label_ar": "المستحق"}, {"key": "overdue", "label_ar": "المتأخر"},
                       {"key": "oldest_unpaid", "label_ar": "أقدم فاتورة غير مسددة"}, {"key": "open_invoices", "label_ar": "فواتير مفتوحة"}],
        table_rows=rows, id_groups={"open_credit_sales": ids}, transactions=_txns_by_ids(session, open_ids),
        ids_truncated=trunc, warnings=warnings, has_data=bool(balances),
    )


def customer_payment_history(session: Session, a: PaymentHistoryArgs) -> ToolResult:
    found = _find_customers(session, a.customer_name)
    if not found:
        return ToolResult(tool="get_customer_payment_history", arguments=a.model_dump(exclude_none=True), title_ar="سجل تسديدات زبون",
                          basis_ar="تسديدات الزبون المسجلة.", has_data=False, warnings=[f"لا يوجد زبون باسم «{a.customer_name}»."])
    if len(found) > 1:
        raise ToolArgError("الاسم غير واضح، يطابق عدة زبائن: " + "، ".join(c.name for c in found[:6]) + ". اسأل المستخدم أي واحد يقصد.")
    cust = found[0]
    resolved = a.resolve(session, required=False)
    ref = get_reference_date(session)
    rng = resolved[0] if resolved else DateRange(ref - timedelta(days=3650), ref)   # 'all time' = the maximum supported span
    pays = customer_payments_in_range(session, rng, cust.id)
    ids, trunc = _cap([p.id for p in pays])
    bal = next(b for b in all_customer_balances(session) if b.customer_id == cust.id)
    rows = [{"date": p.txn_date.isoformat(), "amount": format_iqd(p.amount_iqd), "method": METHOD_AR[p.payment_method.value], "reference": p.reference or ""}
            for p in reversed(pays)]
    return ToolResult(
        tool="get_customer_payment_history", arguments=a.model_dump(exclude_none=True), title_ar=f"تسديدات الزبون {cust.name}",
        basis_ar="مجموع الدفعات المستلمة من الزبون خلال الفترة. الدفعات تخفض الدين ولا تُحسب مبيعات.",
        date_range=rng.to_dict(),
        figures=[_fig("payments_total", "مجموع التسديدات", sum(p.amount_iqd for p in pays)), _fig("payments_count", "عدد الدفعات", len(pays), money=False),
                 Figure("last_payment_date", "تاريخ آخر دفعة", pays[-1].txn_date.isoformat() if pays else None, pays[-1].txn_date.isoformat() if pays else "لا توجد"),
                 _fig("outstanding_now", "الدين الحالي على الزبون", bal.outstanding)],
        table_columns=[{"key": "date", "label_ar": "التاريخ"}, {"key": "amount", "label_ar": "المبلغ"}, {"key": "method", "label_ar": "الطريقة"}, {"key": "reference", "label_ar": "المرجع"}],
        table_rows=rows, id_groups={"customer_payment": ids}, transactions=_txns_by_ids(session, ids), ids_truncated=trunc, has_data=bool(pays),
    )


def recent_transactions(session: Session, a: RecentArgs) -> ToolResult:
    rows_, _ = list_transactions(session, TxnFilters(type=a.type), page=1, page_size=a.limit)
    rows = [{"id": t.id, "date": t.txn_date.isoformat(), "type": TYPE_AR[t.type.value], "amount": format_iqd(t.amount_iqd),
             "method": METHOD_AR[t.payment_method.value], "party": (t.customer.name if t.customer else t.supplier.name if t.supplier else "")}
            for t in rows_]
    ids = [t.id for t in rows_]
    return ToolResult(
        tool="get_recent_transactions", arguments=a.model_dump(exclude_none=True), title_ar="آخر المعاملات",
        basis_ar="أحدث المعاملات المسجلة مرتبة بالتاريخ (الأحدث أولاً).",
        date_range=({"start": rows_[-1].txn_date.isoformat(), "end": rows_[0].txn_date.isoformat(), "days": (rows_[0].txn_date - rows_[-1].txn_date).days + 1} if rows_ else None),
        figures=[_fig("count", "عدد المعاملات المعروضة", len(rows_), money=False)],
        table_columns=[{"key": "id", "label_ar": "رقم"}, {"key": "date", "label_ar": "التاريخ"}, {"key": "type", "label_ar": "النوع"},
                       {"key": "amount", "label_ar": "المبلغ"}, {"key": "method", "label_ar": "الدفع"}, {"key": "party", "label_ar": "الطرف"}],
        table_rows=rows, id_groups={"recent": ids}, transactions=[serialize(t) for t in rows_], has_data=bool(rows_),
    )


def unreconciled(session: Session, a: UnreconciledArgs) -> ToolResult:
    resolved = a.resolve(session, required=False)
    rng = resolved[0] if resolved else None
    flags = detect_anomalies(session, rng)
    ids_all = sorted({f.transaction_id for f in flags})
    txns = {t.id: t for t in session.scalars(select(Transaction).where(Transaction.id.in_(ids_all[:300])))} if ids_all else {}
    rows = [{"id": f.transaction_id, "date": txns[f.transaction_id].txn_date.isoformat(), "amount": format_iqd(txns[f.transaction_id].amount_iqd),
             "issue": FLAG_AR[f.code], "severity": {"high": "عالية", "medium": "متوسطة", "low": "منخفضة"}[f.severity], "detail": f.message_ar}
            for f in flags if f.transaction_id in txns]
    by_code: dict[str, int] = {}
    for f in flags:
        by_code[f.code] = by_code.get(f.code, 0) + 1
    ids, trunc = _cap(ids_all)
    figs = [_fig("flagged_transactions", "عدد المعاملات التي تحتاج مراجعة", len(ids_all), money=False)]
    figs += [_fig(f"flag_{c}", FLAG_AR[c], n, money=False) for c, n in sorted(by_code.items())]
    return ToolResult(
        tool="get_unreconciled_transactions", arguments=a.model_dump(exclude_none=True), title_ar="معاملات تحتاج مراجعة",
        basis_ar="فحص آلي ثابت القواعد: تكرار محتمل، تاريخ مستقبلي، مبلغ أكبر من 5 أضعاف المعتاد، دفعة زائدة، أو معاملة غير مطابقة. هذه تنبيهات للمراجعة وليست حكماً نهائياً.",
        date_range=rng.to_dict() if rng else None, figures=figs,
        table_columns=[{"key": "id", "label_ar": "رقم"}, {"key": "date", "label_ar": "التاريخ"}, {"key": "amount", "label_ar": "المبلغ"},
                       {"key": "issue", "label_ar": "المشكلة"}, {"key": "severity", "label_ar": "الأهمية"}],
        table_rows=rows[:25], id_groups={"flagged": ids}, transactions=_txns_by_ids(session, ids_all), ids_truncated=trunc, has_data=bool(flags),
    )


def _spec_range(session: Session, period, start, end, label: str) -> DateRange | None:
    if period is None and start is None and end is None:
        return None
    return reports.resolve_range(session, period, start, end)[0]


def _default_previous(name: str | None, cur: DateRange, ref) -> DateRange:
    """What people mean by 'compared with before': this month so far vs the same days last month; this/last week vs the
    same days of the previous week; last month vs the month before it; anything else vs the equal span right before."""
    if name == "this_month":
        return named_period("last_month_same_span", ref)
    if name in ("this_week", "last_week"):
        return DateRange(cur.start - timedelta(days=7), cur.end - timedelta(days=7))
    if name == "last_month":
        end = cur.start - timedelta(days=1)
        return DateRange(end.replace(day=1), end)
    return cur.previous()


def compare_periods_tool(session: Session, a: CompareArgs) -> ToolResult:
    ref = get_reference_date(session)
    cur = _spec_range(session, a.current_period, a.current_start, a.current_end, "current")
    if cur is None:
        raise ToolArgError("الفترة الحالية غير محددة. اسأل المستخدم ماذا يريد أن يقارن.")
    prev = _spec_range(session, a.previous_period, a.previous_start, a.previous_end, "previous")
    if prev is None:
        prev = _default_previous(a.current_period, cur, ref)
    cmp = _compare_periods(session, cur, prev, include_ids=True)
    labels = {"sales_total": "المبيعات", "sales_credit": "المبيعات الآجلة", "customer_payments": "تسديدات الزبائن", "expenses_total": "المصاريف التشغيلية",
              "purchases_total": "مشتريات البضاعة", "estimated_profit": "الربح التقديري", "net_cash_flow": "صافي النقد"}
    rows, figs = [], []
    for k, v in cmp.metrics.items():
        pct = f"{v['pct_change']}%" if v["pct_change"] is not None else "غير محسوب (الفترة السابقة صفر)"
        rows.append({"metric": labels[k], "current": format_iqd(v["current"]), "previous": format_iqd(v["previous"]),
                     "change": format_iqd(v["change"]), "pct_change": pct})
    for k in ("sales_total", "estimated_profit"):
        v = cmp.metrics[k]
        figs += [_fig(f"{k}_current", f"{labels[k]} (الحالية)", v["current"]), _fig(f"{k}_previous", f"{labels[k]} (السابقة)", v["previous"]),
                 _fig(f"{k}_change", f"التغير في {labels[k]}", v["change"]),
                 Figure(f"{k}_pct", f"نسبة التغير في {labels[k]}", v["pct_change"], f"{v['pct_change']}%" if v["pct_change"] is not None else "غير محسوب")]
    groups = {}
    for tag, summ in (("current", cmp.current), ("previous", cmp.previous)):
        for t in ("sale", "expense", "supplier_purchase"):
            groups[f"{tag}_{t}"] = summ.transaction_ids.get(t, [])[:MAX_ID_LIST]
    return ToolResult(
        tool="compare_periods", arguments=a.model_dump(exclude_none=True), title_ar="مقارنة فترتين",
        basis_ar="كل فترة تُحسب بنفس قواعد الملخصات. النسبة = (الحالي − السابق) ÷ |السابق|. الربح تقديري.",
        date_range=cur.to_dict(), secondary_range=prev.to_dict(), figures=figs,
        table_columns=[{"key": "metric", "label_ar": "المؤشر"}, {"key": "current", "label_ar": "الحالية"}, {"key": "previous", "label_ar": "السابقة"},
                       {"key": "change", "label_ar": "التغير"}, {"key": "pct_change", "label_ar": "النسبة"}],
        table_rows=rows, id_groups=groups, transactions=_txns_by_ids(session, groups["current_sale"]),
        warnings=([cmp.length_warning] if cmp.length_warning else []) + ["الربح تقديري."], is_estimate=True,
        has_data=bool(cmp.current.transaction_counts or cmp.previous.transaction_counts),
    )


def cashflow_projection(session: Session, a: CashflowArgs) -> ToolResult:
    ref = get_reference_date(session)
    r = project_cashflow(session, ref, horizon_days=a.horizon_days)
    figs = [_fig("outstanding_receivables", "ديون الزبائن المستحقة (غير محسوبة في التوقع)", r["outstanding_receivables"])]
    if r["sufficient_data"]:
        figs = [_fig("projected_net_change", f"التغير المتوقع في النقد خلال {a.horizon_days} يوم (تقدير)", r["projected_net_change"]),
                _fig("low", "الحد الأدنى التقريبي", r["low"]), _fig("high", "الحد الأعلى التقريبي", r["high"]),
                _fig("avg_daily_cash_in", "متوسط المقبوض اليومي", r["avg_daily_cash_in"]), _fig("avg_daily_cash_out", "متوسط المدفوع اليومي", r["avg_daily_cash_out"])] + figs
    return ToolResult(
        tool="get_cashflow_projection", arguments=a.model_dump(exclude_none=True), title_ar="توقع التدفق النقدي (تقدير)",
        basis_ar="متوسط صافي النقد اليومي خلال آخر 56 يوماً × عدد أيام التوقع. المدى = تذبذب أسبوعي تقريبي وليس فاصل ثقة. هو تغيّر في النقد وليس رصيداً.",
        date_range=r["lookback"], figures=figs, warnings=[r["disclaimer_ar"]] + ([r["note_ar"]] if not r["sufficient_data"] else []),
        is_estimate=True, has_data=r["sufficient_data"], evidence_kind="aggregate",
    )


def top_customers(session: Session, a: TopCustomersArgs) -> ToolResult:
    rng, _ = a.resolve(session)
    top = top_customers_by_sales(session, rng, a.limit)
    ids = [i for t in top for i in t["transaction_ids"]]
    cap, trunc = _cap(ids)
    rows = [{"rank": i + 1, "customer": t["name"], "total": format_iqd(t["total"]), "invoices": len(t["transaction_ids"])} for i, t in enumerate(top)]
    return ToolResult(
        tool="get_top_customers", arguments=a.model_dump(exclude_none=True), title_ar="أكثر الزبائن شراءً",
        basis_ar="ترتيب الزبائن المسجلين بمجموع مشترياتهم (كل طرق الدفع) خلال الفترة. المبيعات النقدية بدون اسم زبون غير مشمولة.",
        date_range=rng.to_dict(), figures=[_fig("customers_count", "عدد الزبائن في القائمة", len(top), money=False)],
        table_columns=[{"key": "rank", "label_ar": "الترتيب"}, {"key": "customer", "label_ar": "الزبون"}, {"key": "total", "label_ar": "إجمالي المشتريات"}, {"key": "invoices", "label_ar": "عدد الفواتير"}],
        table_rows=rows, id_groups={"sale": cap}, transactions=_txns_by_ids(session, cap), ids_truncated=trunc, has_data=bool(top),
    )


# ----------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[..., ToolResult]


_SPECS = [
    ToolSpec("get_sales_summary", "Total sales (revenue) for a period: cash, wallet/bank and credit sales. Use for 'how much did I sell'.", PeriodArgs, sales_summary),
    ToolSpec("get_expenses_summary", "Operating expenses (by category), stock purchases and supplier payments for a period.", PeriodArgs, expenses_summary),
    ToolSpec("get_profit_summary", "ESTIMATED profit (sales - purchases - expenses) and net cash for a period. Use for 'how much did I earn/profit'.", PeriodArgs, profit_summary),
    ToolSpec("get_customer_debts", "Customers who currently owe money (who hasn't paid), total debt and overdue amounts. Optional customer name filter.", DebtsArgs, customer_debts),
    ToolSpec("get_customer_payment_history", "Payments received from ONE named customer (optionally within a period).", PaymentHistoryArgs, customer_payment_history),
    ToolSpec("get_recent_transactions", "The latest recorded transactions, optionally of one type.", RecentArgs, recent_transactions),
    ToolSpec("get_unreconciled_transactions", "Transactions needing review: possible duplicates, unusual amounts, future dates, unreconciled payments.", UnreconciledArgs, unreconciled),
    ToolSpec("compare_periods", "Compare two periods (e.g. this month vs last month). If previous is omitted a sensible default is used.", CompareArgs, compare_periods_tool),
    ToolSpec("get_cashflow_projection", "ESTIMATED cash-flow change for the next N days (default 30) from recent activity.", CashflowArgs, cashflow_projection),
    ToolSpec("get_top_customers", "Customers ranked by how much they bought in a period.", TopCustomersArgs, top_customers),
]
REGISTRY: dict[str, ToolSpec] = {s.name: s for s in _SPECS}


def _clean_schema(node):
    """Flatten pydantic's schema (anyOf-null, titles, $defs) into the plain form every provider accepts."""
    if isinstance(node, dict):
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            merged = {k: v for k, v in node.items() if k not in ("anyOf", "default", "title")}
            if len(options) == 1:
                merged.update(_clean_schema(options[0]))
            return merged
        return {k: _clean_schema(v) for k, v in node.items() if k not in ("title", "default")}
    if isinstance(node, list):
        return [_clean_schema(x) for x in node]
    return node


def _inline_refs(schema: dict) -> dict:
    defs = schema.pop("$defs", {})

    def walk(n):
        if isinstance(n, dict):
            if "$ref" in n:
                return walk(dict(defs[n["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in n.items()}
        if isinstance(n, list):
            return [walk(x) for x in n]
        return n

    return walk(schema)


def tool_schemas() -> list[dict]:
    out = []
    for s in _SPECS:
        params = _clean_schema(_inline_refs(s.args_model.model_json_schema()))
        params.setdefault("properties", {})
        params["additionalProperties"] = False
        out.append({"type": "function", "function": {"name": s.name, "description": s.description, "parameters": params}})
    return out


def validate_args(spec: ToolSpec, raw: dict) -> BaseModel:
    try:
        return spec.args_model.model_validate(raw)
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'arguments'}: {err['msg']}" for err in e.errors())
        raise ToolArgError(f"وسائط غير صالحة: {msgs}") from None


def execute(session: Session, name: str, raw_args: dict) -> ToolResult:
    """Validate and run one allowlisted tool. Raises ToolArgError / InvalidDateRange on bad input."""
    from app.ai.readonly import read_only

    spec = REGISTRY.get(name)
    if spec is None:
        raise ToolArgError(f"أداة غير معروفة: {name}. الأدوات المتاحة: {', '.join(REGISTRY)}")
    args = validate_args(spec, raw_args)
    with read_only():
        return spec.handler(session, args)
