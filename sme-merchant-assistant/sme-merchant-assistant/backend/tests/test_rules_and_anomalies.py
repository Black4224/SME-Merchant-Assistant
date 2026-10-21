from datetime import date

import pytest

from app.models import PaymentMethod as PM
from app.models import TransactionType as TT
from app.services.anomalies import detect_anomalies
from app.services.money import InvalidAmount
from app.services.periods import DateRange
from app.services.transactions import BusinessRuleError, add_transaction, check_transaction_rules

D = date


# ---------------- business-rule validation ----------------
@pytest.mark.parametrize(
    "ttype,method,cust,supp",
    [
        (TT.SALE, PM.CREDIT, None, None),                 # credit sale needs customer
        (TT.SALE, PM.CASH, None, 1),                      # sale never has a supplier
        (TT.CUSTOMER_PAYMENT, PM.CASH, None, None),       # payment needs customer
        (TT.CUSTOMER_PAYMENT, PM.CREDIT, 1, None),        # payment can't be credit
        (TT.SUPPLIER_PURCHASE, PM.CREDIT, None, None),    # credit purchase needs supplier
        (TT.SUPPLIER_PURCHASE, PM.CASH, 1, None),
        (TT.SUPPLIER_PAYMENT, PM.CASH, None, None),
        (TT.SUPPLIER_PAYMENT, PM.CREDIT, None, 1),
        (TT.EXPENSE, PM.CREDIT, None, None),
        (TT.EXPENSE, PM.CASH, 1, None),
    ],
)
def test_invalid_combinations_rejected(ttype, method, cust, supp):
    with pytest.raises(BusinessRuleError):
        check_transaction_rules(type=ttype, payment_method=method, customer_id=cust, supplier_id=supp)


def test_valid_combinations_accepted():
    ok = check_transaction_rules
    ok(type=TT.SALE, payment_method=PM.CASH, customer_id=None, supplier_id=None)
    ok(type=TT.SALE, payment_method=PM.CREDIT, customer_id=1, supplier_id=None)
    ok(type=TT.CUSTOMER_PAYMENT, payment_method=PM.DIGITAL, customer_id=1, supplier_id=None)
    ok(type=TT.SUPPLIER_PURCHASE, payment_method=PM.CREDIT, customer_id=None, supplier_id=1)
    ok(type=TT.SUPPLIER_PAYMENT, payment_method=PM.BANK, customer_id=None, supplier_id=1)
    ok(type=TT.EXPENSE, payment_method=PM.CASH, customer_id=None, supplier_id=None)


def test_add_transaction_validates_amount_description_and_party(session, parties):
    base = dict(txn_date=D(2026, 10, 1), type=TT.SALE, payment_method=PM.CASH)
    with pytest.raises(InvalidAmount):
        add_transaction(session, amount=-5, description="x", **base)
    with pytest.raises(InvalidAmount):
        add_transaction(session, amount=12.5, description="x", **base)
    with pytest.raises(BusinessRuleError):
        add_transaction(session, amount=100, description="   ", **base)
    with pytest.raises(BusinessRuleError):
        add_transaction(session, amount=100, description="x" * 256, **base)
    with pytest.raises(BusinessRuleError):
        add_transaction(session, amount=100, description="x", customer_id=9999, **{**base, "payment_method": PM.CREDIT})


def test_dedup_seq_increments_for_identical_content(session, txn):
    a = txn(D(2026, 10, 1), "sale", 5_000, desc="same")
    b = txn(D(2026, 10, 1), "sale", 5_000, desc="same")
    c = txn(D(2026, 10, 1), "sale", 5_001, desc="same")
    assert a.dedup_key == b.dedup_key and (a.dedup_seq, b.dedup_seq) == (1, 2)
    assert c.dedup_key != a.dedup_key and c.dedup_seq == 1


def test_dedup_key_ignores_arabic_spelling_variants(session, txn):
    a = txn(D(2026, 10, 1), "sale", 5_000, desc="بيع أحمد")
    b = txn(D(2026, 10, 1), "sale", 5_000, desc="بيع احمد")
    assert a.dedup_key == b.dedup_key


# ---------------- anomaly / reconciliation flags ----------------
def codes(flags):
    return sorted((f.transaction_id, f.code) for f in flags)


def test_possible_duplicate_flags_only_the_later_row(session, txn):
    a = txn(D(2026, 10, 1), "sale", 5_000, desc="x", reference="INV-1")
    b = txn(D(2026, 10, 1), "sale", 5_000, desc="x", reference="INV-1")
    flags = detect_anomalies(session)
    assert codes(flags) == [(b.id, "possible_duplicate")]
    assert flags[0].related_ids == (a.id,)


def test_different_reference_is_not_duplicate(session, txn):
    txn(D(2026, 10, 1), "sale", 5_000, desc="x", reference="INV-1")
    txn(D(2026, 10, 1), "sale", 5_000, desc="x", reference="INV-2")
    assert detect_anomalies(session) == []


def test_excluded_duplicate_is_not_flagged(session, txn):
    txn(D(2026, 10, 1), "sale", 5_000, desc="x")
    txn(D(2026, 10, 1), "sale", 5_000, desc="x", status="excluded")
    assert detect_anomalies(session) == []


def test_amount_outlier_needs_enough_history_and_10x_typo_is_caught(session, txn):
    for m in range(1, 5):
        txn(D(2026, 6 + m - 1, 5), "expense", 400_000, desc=f"gen {m}")
    typo = txn(D(2026, 10, 5), "expense", 4_000_000, desc="gen typo")
    assert codes(detect_anomalies(session)) == [(typo.id, "amount_outlier")]


def test_outlier_skipped_with_too_little_history(session, txn):
    txn(D(2026, 10, 1), "expense", 1_000, desc="a")
    txn(D(2026, 10, 2), "expense", 900_000, desc="b")
    assert detect_anomalies(session) == []


def test_large_customer_payment_is_not_an_outlier(session, txn, parties):
    c1, _, _ = parties
    for i in range(6):
        txn(D(2026, 10, 1 + i), "sale", 1_000_000 if i == 5 else 10_000, "credit", customer_id=c1.id, desc=f"s{i}")
    pay = txn(D(2026, 10, 10), "customer_payment", 1_000_000, "cash", customer_id=c1.id)
    flagged = {(f.transaction_id, f.code) for f in detect_anomalies(session)}
    assert (pay.id, "amount_outlier") not in flagged      # payments are balance-driven, never outliers
    assert any(code == "amount_outlier" for _, code in flagged)  # ...but the 100x credit SALE is


def test_future_date_and_unreconciled_flags(session, txn):
    f = txn(D(2026, 10, 18), "sale", 1_000, desc="future")  # reference date is 2026-10-15
    u = txn(D(2026, 10, 14), "sale", 2_000, desc="unrec", status="unreconciled")
    assert codes(detect_anomalies(session)) == [(f.id, "future_date"), (u.id, "unreconciled")]


def test_customer_overpayment_flag(session, txn, parties):
    c1, _, _ = parties
    txn(D(2026, 10, 1), "sale", 50_000, "credit", customer_id=c1.id)
    p = txn(D(2026, 10, 2), "customer_payment", 80_000, "cash", customer_id=c1.id)
    assert codes(detect_anomalies(session)) == [(p.id, "customer_overpayment")]


def test_range_filter_and_severity_order(session, txn):
    old = txn(D(2026, 9, 1), "sale", 1_000, desc="old", status="unreconciled")
    dup1 = txn(D(2026, 10, 1), "sale", 5_000, desc="d")
    dup2 = txn(D(2026, 10, 1), "sale", 5_000, desc="d")
    unrec = txn(D(2026, 10, 2), "sale", 7_000, desc="u", status="unreconciled")
    everything = detect_anomalies(session)
    assert [f.severity for f in everything] == ["high", "low", "low"]
    in_oct = detect_anomalies(session, DateRange(D(2026, 10, 1), D(2026, 10, 31)))
    assert {f.transaction_id for f in in_oct} == {dup2.id, unrec.id}
    assert old.id not in {f.transaction_id for f in in_oct}
