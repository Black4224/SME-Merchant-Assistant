"""Independent ground truth. Reads ONLY the raw CSV with the standard library and shares no code with `app/`.
If this module and the application disagree, one of them has a bug - tests/test_eval_dataset.py checks that they agree."""
import csv
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "sample_transactions.csv"
REF = date(2026, 10, 15)  # the demo's pinned "today" (a Thursday); weeks start on Sunday
CREDIT_TERMS_DAYS = 30


def load(path: Path = CSV_PATH) -> list[dict]:
    """Row ids are 1-based file order, which is exactly the order the seed script inserts them."""
    out = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f), 1):
            out.append({"id": i, "date": date.fromisoformat(r["date"]), "type": r["type"], "amount": int(r["amount"]),
                        "method": r["payment_method"], "customer": r["customer"], "supplier": r["supplier"],
                        "category": r["category"], "status": r["status"], "description": r["description"], "reference": r["reference"]})
    return out


def _last_day(y: int, m: int) -> int:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - timedelta(days=1)).day


def period(name: str, ref: date = REF) -> tuple[date, date]:
    if name == "today":
        return ref, ref
    if name == "yesterday":
        return ref - timedelta(days=1), ref - timedelta(days=1)
    sunday = ref - timedelta(days=(ref.weekday() + 1) % 7)
    if name == "this_week":
        return sunday, ref
    if name == "last_week":
        return sunday - timedelta(days=7), sunday - timedelta(days=1)
    if name == "this_month":
        return ref.replace(day=1), ref
    py, pm = (ref.year - 1, 12) if ref.month == 1 else (ref.year, ref.month - 1)
    if name == "last_month":
        return date(py, pm, 1), date(py, pm, _last_day(py, pm))
    if name == "last_month_same_span":
        return date(py, pm, 1), date(py, pm, min(ref.day, _last_day(py, pm)))
    if name == "last_7_days":
        return ref - timedelta(days=6), ref
    if name == "last_30_days":
        return ref - timedelta(days=29), ref
    raise ValueError(name)


def previous_equal_span(start: date, end: date) -> tuple[date, date]:
    n = (end - start).days + 1
    return start - timedelta(days=n), start - timedelta(days=1)


def _active(rows, start, end):
    return [r for r in rows if start <= r["date"] <= end and r["status"] != "excluded"]


def summarize(rows, start: date, end: date) -> dict:
    s = defaultdict(int)
    ids = defaultdict(list)
    for r in _active(rows, start, end):
        t, a, m = r["type"], r["amount"], r["method"]
        ids[t].append(r["id"])
        if t == "sale":
            s["sales"] += a
            s["sales_credit" if m == "credit" else "sales_collected"] += a
        elif t == "customer_payment":
            s["payments"] += a
        elif t == "expense":
            s["expenses"] += a
        elif t == "supplier_purchase":
            s["purchases"] += a
            if m == "credit":
                s["purchases_credit"] += a
        elif t == "supplier_payment":
            s["supplier_payments"] += a
    s["profit"] = s["sales"] - s["purchases"] - s["expenses"]
    s["cash_in"] = s["sales_collected"] + s["payments"]
    s["cash_out"] = s["expenses"] + s["purchases"] - s["purchases_credit"] + s["supplier_payments"]
    s["net_cash"] = s["cash_in"] - s["cash_out"]
    s["ids"] = {k: sorted(v) for k, v in ids.items()}
    s["count"] = {k: len(v) for k, v in ids.items()}
    return dict(s)


def debts(rows, ref: date = REF) -> dict[str, dict]:
    """Per customer: FIFO allocation of payments to the oldest credit sale; overdue = remainder older than 30 days."""
    ev = defaultdict(list)
    for r in rows:
        if r["status"] == "excluded" or not r["customer"] or r["date"] > ref:
            continue
        if (r["type"] == "sale" and r["method"] == "credit") or r["type"] == "customer_payment":
            ev[r["customer"]].append(r)
    out = {}
    for name, items in ev.items():
        items.sort(key=lambda r: (r["date"], r["id"]))
        open_inv, paid, pay_ids, last_pay, credit = [], 0, [], None, 0
        for r in items:
            if r["type"] == "sale":
                open_inv.append([r, r["amount"]])
                credit += r["amount"]
            else:
                paid += r["amount"]
                pay_ids.append(r["id"])
                last_pay = r["date"]
                left = r["amount"]
                for inv in open_inv:
                    take = min(inv[1], left)
                    inv[1] -= take
                    left -= take
        remaining = [(r, rem) for r, rem in open_inv if rem > 0]
        out[name] = {"outstanding": credit - paid, "credit_sales": credit, "payments_total": paid, "payments_count": len(pay_ids),
                     "payment_ids": sorted(pay_ids), "last_payment": last_pay,
                     "overdue": sum(rem for r, rem in remaining if (ref - r["date"]).days > CREDIT_TERMS_DAYS),
                     "open_ids": sorted(r["id"] for r, _ in remaining)}
    return out


def top_customers(rows, start: date, end: date):
    tot = defaultdict(int)
    for r in _active(rows, start, end):
        if r["type"] == "sale" and r["customer"]:
            tot[r["customer"]] += r["amount"]
    return sorted(tot.items(), key=lambda kv: (-kv[1], kv[0]))


def cashflow(rows, horizon: int = 30, lookback: int = 56, ref: date = REF) -> int:
    start = ref - timedelta(days=lookback - 1)
    total = summarize(rows, start, ref)["net_cash"]
    q = Fraction(abs(total) * horizon, lookback) + Fraction(1, 2)
    return (1 if total >= 0 else -1) * int(q)  # floor of (|x| + 1/2) = round half away from zero


def recent(rows, n: int, type_: str | None = None) -> list[int]:
    pool = [r for r in rows if r["status"] != "excluded" and (type_ is None or r["type"] == type_)]
    return [r["id"] for r in sorted(pool, key=lambda r: (r["date"], r["id"]), reverse=True)[:n]]


def pct_change(cur: int, prev: int) -> str | None:
    if prev == 0:
        return None
    return str((Decimal(cur - prev) * 100 / Decimal(abs(prev))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def unreconciled_ids(rows) -> list[int]:
    return sorted(r["id"] for r in rows if r["status"] == "unreconciled")
