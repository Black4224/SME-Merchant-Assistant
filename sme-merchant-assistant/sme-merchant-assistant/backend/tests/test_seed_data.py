"""The synthetic dataset must be reproducible, internally consistent, and every
service figure must match an independent re-computation from the raw CSV."""
import csv
from collections import defaultdict
from datetime import date, timedelta

from app.config import DATA_DIR
from app.services.anomalies import detect_anomalies
from app.services.customers import all_customer_balances
from app.services.metrics import summarize_period
from app.services.periods import DateRange, named_period
from app.services.settings_service import get_setting
from scripts.seed_demo import DEFAULT_END_DATE, build_dataset, write_csv

REF = DEFAULT_END_DATE


def test_dataset_is_deterministic():
    assert build_dataset() == build_dataset()
    assert build_dataset(seed=1) != build_dataset()


def test_committed_sample_csv_matches_generator(tmp_path):
    fresh = tmp_path / "fresh.csv"
    write_csv(build_dataset(), fresh)
    assert fresh.read_bytes() == (DATA_DIR / "sample_transactions.csv").read_bytes()


def test_dataset_covers_three_plus_months_and_all_types():
    rows = build_dataset()
    dates = sorted(r["date"] for r in rows)
    assert (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days >= 90
    assert {r["type"] for r in rows} == {"sale", "customer_payment", "expense", "supplier_purchase", "supplier_payment"}
    assert {r["payment_method"] for r in rows} == {"cash", "digital", "bank", "credit"}


def test_seed_marks_demo_data_and_pins_reference_date(seeded):
    assert get_setting(seeded, "is_demo_data") == "true"
    assert get_setting(seeded, "reference_date") == REF.isoformat()


def test_no_customer_is_overpaid_by_the_generator_itself(seeded):
    # the only overpayment-type problems in the data would be planted ones; there are none
    assert all(b.outstanding >= 0 for b in all_customer_balances(seeded))
    assert sum(1 for b in all_customer_balances(seeded) if b.outstanding > 0) >= 3  # several debtors
    assert any(b.overdue_amount > 0 for b in all_customer_balances(seeded))


def test_planted_anomalies_are_detected(seeded):
    codes = {f.code for f in detect_anomalies(seeded)}
    assert {"possible_duplicate", "amount_outlier", "future_date", "unreconciled"} <= codes
    by_code = defaultdict(int)
    for f in detect_anomalies(seeded):
        by_code[f.code] += 1
    assert by_code["possible_duplicate"] == 1 and by_code["amount_outlier"] == 1 and by_code["future_date"] == 1


# ---------- independent oracle: plain csv + python, no app code ----------
def _csv_rows():
    with (DATA_DIR / "sample_transactions.csv").open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _oracle(rows, start: date, end: date) -> dict:
    o = dict(sales=0, credit=0, payments=0, expenses=0, purchases=0, supplier_pay=0, cash_in=0, cash_out=0)
    for r in rows:
        d = date.fromisoformat(r["date"])
        if not (start <= d <= end) or r["status"] == "excluded":
            continue
        amt, method = int(r["amount"]), r["payment_method"]
        t = r["type"]
        if t == "sale":
            o["sales"] += amt
            if method == "credit":
                o["credit"] += amt
            else:
                o["cash_in"] += amt
        elif t == "customer_payment":
            o["payments"] += amt
            o["cash_in"] += amt
        elif t == "expense":
            o["expenses"] += amt
            o["cash_out"] += amt
        elif t == "supplier_purchase":
            o["purchases"] += amt
            if method != "credit":
                o["cash_out"] += amt
        elif t == "supplier_payment":
            o["supplier_pay"] += amt
            o["cash_out"] += amt
    return o


def test_every_period_matches_independent_oracle(seeded):
    rows = _csv_rows()
    periods = [named_period(n, REF) for n in ("today", "yesterday", "this_week", "last_week", "this_month", "last_month", "last_30_days")]
    periods.append(DateRange(REF - timedelta(days=200), REF + timedelta(days=10)))  # whole dataset incl. future typo
    for p in periods:
        m, o = summarize_period(seeded, p), _oracle(rows, p.start, p.end)
        assert (m.sales_total, m.sales_credit, m.customer_payments) == (o["sales"], o["credit"], o["payments"]), p
        assert (m.expenses_total, m.purchases_total, m.supplier_payments) == (o["expenses"], o["purchases"], o["supplier_pay"]), p
        assert (m.cash_in, m.cash_out) == (o["cash_in"], o["cash_out"]), p
        assert m.estimated_profit == o["sales"] - o["purchases"] - o["expenses"], p


def test_customer_balances_match_oracle_and_ids_are_traceable(seeded):
    delta = defaultdict(int)
    for r in _csv_rows():
        if r["type"] == "sale" and r["payment_method"] == "credit":
            delta[r["customer"]] += int(r["amount"])
        elif r["type"] == "customer_payment":
            delta[r["customer"]] -= int(r["amount"])
    balances = {b.name: b for b in all_customer_balances(seeded)}
    assert {n: b.outstanding for n, b in balances.items() if n in delta} == dict(delta)
    # traceability: remaining open invoices add up to the outstanding balance
    for b in balances.values():
        assert sum(i.remaining for i in b.open_invoices) == max(b.outstanding, 0)
        assert b.overdue_amount <= max(b.outstanding, 0)
        assert len(b.credit_sale_ids) >= len(b.open_invoices)


def test_ids_reported_in_summary_sum_to_the_total(seeded):
    from sqlalchemy import select

    from app.models import Transaction

    m = summarize_period(seeded, named_period("last_month", REF))
    amounts = dict(seeded.execute(select(Transaction.id, Transaction.amount_iqd)).all())
    types = {"sale": m.sales_total, "expense": m.expenses_total, "supplier_purchase": m.purchases_total}
    for t, total in types.items():
        assert sum(amounts[i] for i in m.transaction_ids[t]) == total
