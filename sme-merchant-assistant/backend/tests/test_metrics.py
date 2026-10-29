"""Hand-computed expectations for the business rules."""
from datetime import date, timedelta

from app.services.metrics import daily_series, summarize_period
from app.services.periods import DateRange

D = date


def _scenario(txn, parties):
    c1, c2, s1 = parties
    # Oct 10: 100k cash sale, 50k wallet sale, 200k credit sale (c1)
    txn(D(2026, 10, 10), "sale", 100_000, "cash")
    txn(D(2026, 10, 10), "sale", 50_000, "digital")
    txn(D(2026, 10, 10), "sale", 200_000, "credit", customer_id=c1.id)
    # Oct 11: c1 pays 80k (NOT a sale), rent 30k, stock 120k cash + 300k on credit, pay supplier 100k
    txn(D(2026, 10, 11), "customer_payment", 80_000, "cash", customer_id=c1.id)
    txn(D(2026, 10, 11), "expense", 30_000, "cash")
    txn(D(2026, 10, 11), "supplier_purchase", 120_000, "cash", supplier_id=s1.id)
    txn(D(2026, 10, 11), "supplier_purchase", 300_000, "credit", supplier_id=s1.id)
    txn(D(2026, 10, 11), "supplier_payment", 100_000, "bank", supplier_id=s1.id)
    # outside the range
    txn(D(2026, 10, 9), "sale", 999_999, "cash")
    txn(D(2026, 10, 12), "sale", 888_888, "cash")


def test_sales_revenue_includes_credit_but_not_customer_payments(session, txn, parties):
    _scenario(txn, parties)
    m = summarize_period(session, DateRange(D(2026, 10, 10), D(2026, 10, 11)))
    assert m.sales_total == 350_000          # 100k + 50k + 200k, payment of 80k excluded
    assert m.sales_collected == 150_000
    assert m.sales_credit == 200_000
    assert m.customer_payments == 80_000


def test_expenses_purchases_and_supplier_payments_are_distinct(session, txn, parties):
    _scenario(txn, parties)
    m = summarize_period(session, DateRange(D(2026, 10, 10), D(2026, 10, 11)))
    assert m.expenses_total == 30_000
    assert m.purchases_total == 420_000      # cash + credit purchase both booked as cost
    assert m.purchases_credit == 300_000
    assert m.supplier_payments == 100_000    # settles credit; NOT added to costs


def test_profit_is_estimate_without_double_counting_supplier_payment(session, txn, parties):
    _scenario(txn, parties)
    m = summarize_period(session, DateRange(D(2026, 10, 10), D(2026, 10, 11)))
    assert m.estimated_profit == 350_000 - 420_000 - 30_000  # = -100_000
    assert m.profit_basis == "purchases_basis_estimate"
    assert "تقديري" in m.profit_note


def test_cash_flow_differs_from_profit(session, txn, parties):
    _scenario(txn, parties)
    m = summarize_period(session, DateRange(D(2026, 10, 10), D(2026, 10, 11)))
    assert m.cash_in == 150_000 + 80_000
    assert m.cash_out == 30_000 + 120_000 + 100_000   # credit purchase not yet paid
    assert m.net_cash_flow == 230_000 - 250_000
    assert m.net_cash_flow != m.estimated_profit


def test_date_boundaries_are_inclusive(session, txn):
    for day in (9, 10, 11, 12):
        txn(D(2026, 10, day), "sale", 1_000 * day)
    m = summarize_period(session, DateRange(D(2026, 10, 10), D(2026, 10, 11)))
    assert m.sales_total == 10_000 + 11_000
    assert m.transaction_counts == {"sale": 2}
    single = summarize_period(session, DateRange(D(2026, 10, 12), D(2026, 10, 12)))
    assert single.sales_total == 12_000


def test_excluded_rows_are_ignored_and_reported(session, txn):
    txn(D(2026, 10, 10), "sale", 5_000)
    txn(D(2026, 10, 10), "sale", 5_000, desc="dup", status="excluded")
    m = summarize_period(session, DateRange(D(2026, 10, 10), D(2026, 10, 10)))
    assert m.sales_total == 5_000 and m.excluded_count == 1


def test_transaction_ids_support_traceability(session, txn):
    a = txn(D(2026, 10, 10), "sale", 5_000)
    b = txn(D(2026, 10, 10), "expense", 1_000)
    m = summarize_period(session, DateRange(D(2026, 10, 10), D(2026, 10, 10)))
    assert m.transaction_ids == {"sale": [a.id], "expense": [b.id]}
    assert summarize_period(session, DateRange(D(2026, 10, 10), D(2026, 10, 10)), include_ids=False).transaction_ids == {}


def test_empty_period_is_all_zero(session):
    m = summarize_period(session, DateRange(D(2026, 1, 1), D(2026, 1, 31)))
    assert (m.sales_total, m.expenses_total, m.estimated_profit, m.net_cash_flow) == (0, 0, 0, 0)


def test_daily_series_has_every_day_and_matches_summary(session, txn):
    txn(D(2026, 10, 10), "sale", 7_000)
    txn(D(2026, 10, 12), "expense", 2_000)
    r = DateRange(D(2026, 10, 10), D(2026, 10, 13))
    series = daily_series(session, r)
    assert [d["date"] for d in series] == ["2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13"]
    assert series[1] == {"date": "2026-10-11", "sales": 0, "expenses": 0, "purchases": 0, "cash_in": 0, "cash_out": 0}
    m = summarize_period(session, r)
    assert sum(d["sales"] for d in series) == m.sales_total
    assert sum(d["cash_in"] - d["cash_out"] for d in series) == m.net_cash_flow
