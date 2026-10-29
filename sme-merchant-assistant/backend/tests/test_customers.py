from datetime import date

from app.services.customers import (
    all_customer_balances,
    customer_ledger,
    customers_with_debt,
    top_customers_by_sales,
    total_outstanding,
)
from app.services.periods import DateRange
from app.services.suppliers import supplier_payables

D = date


def test_credit_sale_creates_debt_cash_sale_does_not(session, txn, parties):
    c1, c2, _ = parties
    txn(D(2026, 10, 1), "sale", 100_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 1), "sale", 70_000, "cash", customer_id=c2.id)  # named customer, paid in cash
    owing = {b.name: b.outstanding for b in customers_with_debt(session)}
    assert owing == {"زبون أ": 100_000}


def test_payment_reduces_debt_and_is_not_a_sale(session, txn, parties):
    c1, _, _ = parties
    txn(D(2026, 10, 1), "sale", 300_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 5), "customer_payment", 120_000, "cash", customer_id=c1.id)
    b = next(x for x in all_customer_balances(session) if x.customer_id == c1.id)
    assert (b.credit_sales_total, b.payments_total, b.outstanding) == (300_000, 120_000, 180_000)
    assert b.last_payment_date == D(2026, 10, 5)


def test_fifo_allocation_and_overdue(session, txn, parties):
    c1, _, _ = parties
    old = txn(D(2026, 8, 1), "sale", 100_000, "credit", customer_id=c1.id, desc="old")      # 75 days old
    mid = txn(D(2026, 9, 20), "sale", 50_000, "credit", customer_id=c1.id, desc="mid")      # 25 days old
    txn(D(2026, 9, 25), "customer_payment", 60_000, "cash", customer_id=c1.id)              # clears old 60k
    b = next(x for x in all_customer_balances(session) if x.customer_id == c1.id)
    assert b.outstanding == 90_000
    remaining = {i.transaction_id: i.remaining for i in b.open_invoices}
    assert remaining == {old.id: 40_000, mid.id: 50_000}
    assert b.overdue_amount == 40_000          # only the old remainder is past 30 days
    assert b.oldest_unpaid_date == D(2026, 8, 1)


def test_fully_paid_invoice_is_closed(session, txn, parties):
    c1, _, _ = parties
    txn(D(2026, 10, 1), "sale", 100_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 2), "customer_payment", 100_000, "digital", customer_id=c1.id)
    b = all_customer_balances(session)[0]
    assert b.outstanding == 0 and b.open_invoices == [] and customers_with_debt(session) == []


def test_as_of_ignores_later_transactions(session, txn, parties):
    c1, _, _ = parties
    txn(D(2026, 10, 1), "sale", 100_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 10), "customer_payment", 100_000, "cash", customer_id=c1.id)
    assert total_outstanding(session, D(2026, 10, 5)) == 100_000
    assert total_outstanding(session, D(2026, 10, 10)) == 0


def test_ledger_running_balance_and_clear_distinction(session, txn, parties):
    c1, _, _ = parties
    txn(D(2026, 10, 1), "sale", 100_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 3), "customer_payment", 30_000, "cash", customer_id=c1.id)
    txn(D(2026, 10, 4), "sale", 20_000, "credit", customer_id=c1.id)
    ledger = customer_ledger(session, c1.id)
    assert [(e.kind, e.balance_after) for e in ledger] == [
        ("credit_sale", 100_000), ("payment", 70_000), ("credit_sale", 90_000)
    ]


def test_excluded_rows_do_not_affect_debt(session, txn, parties):
    c1, _, _ = parties
    txn(D(2026, 10, 1), "sale", 100_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 1), "sale", 100_000, "credit", customer_id=c1.id, status="excluded")
    assert total_outstanding(session) == 100_000


def test_overpayment_gives_negative_balance_and_is_not_listed_as_debt(session, txn, parties):
    c1, _, _ = parties
    txn(D(2026, 10, 1), "sale", 50_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 2), "customer_payment", 80_000, "cash", customer_id=c1.id)
    assert all_customer_balances(session)[0].outstanding == -30_000
    assert customers_with_debt(session) == [] and total_outstanding(session) == 0


def test_debts_sorted_largest_first(session, txn, parties):
    c1, c2, _ = parties
    txn(D(2026, 10, 1), "sale", 10_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 1), "sale", 90_000, "credit", customer_id=c2.id)
    assert [b.name for b in customers_with_debt(session)] == ["زبون ب", "زبون أ"]


def test_top_customers_counts_all_payment_methods(session, txn, parties):
    c1, c2, _ = parties
    txn(D(2026, 10, 1), "sale", 10_000, "credit", customer_id=c1.id)
    txn(D(2026, 10, 2), "sale", 15_000, "cash", customer_id=c1.id)
    txn(D(2026, 10, 2), "sale", 20_000, "cash", customer_id=c2.id)
    top = top_customers_by_sales(session, DateRange(D(2026, 10, 1), D(2026, 10, 31)))
    assert [(t["name"], t["total"]) for t in top] == [("زبون أ", 25_000), ("زبون ب", 20_000)]
    assert len(top[0]["transaction_ids"]) == 2


def test_supplier_payables(session, txn, parties):
    _, _, s1 = parties
    txn(D(2026, 10, 1), "supplier_purchase", 500_000, "credit", supplier_id=s1.id)
    txn(D(2026, 10, 2), "supplier_purchase", 200_000, "cash", supplier_id=s1.id)   # paid now: no payable
    txn(D(2026, 10, 3), "supplier_payment", 150_000, "cash", supplier_id=s1.id)
    assert supplier_payables(session)[0]["outstanding"] == 350_000
