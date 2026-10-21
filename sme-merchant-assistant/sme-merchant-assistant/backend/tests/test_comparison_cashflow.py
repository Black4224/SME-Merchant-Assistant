from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.cashflow import project_cashflow
from app.services.comparison import compare_periods, pct_change
from app.services.periods import DateRange

D = date


def test_pct_change_values_and_zero_base():
    assert pct_change(150, 100) == Decimal("50.0")
    assert pct_change(50, 100) == Decimal("-50.0")
    assert pct_change(1, 3) == Decimal("-66.7")
    assert pct_change(100, 0) is None
    assert pct_change(-50, -100) == Decimal("50.0")   # loss shrank by half => +50 on |base|


def test_compare_periods_month_over_month(session, txn):
    txn(D(2026, 9, 10), "sale", 1_000_000)
    txn(D(2026, 9, 20), "expense", 200_000)
    txn(D(2026, 10, 5), "sale", 1_500_000)
    txn(D(2026, 10, 6), "expense", 100_000)
    txn(D(2026, 10, 20), "sale", 777)   # later than the compared span - must be ignored
    cmp = compare_periods(session, DateRange(D(2026, 10, 1), D(2026, 10, 15)), DateRange(D(2026, 9, 1), D(2026, 9, 15)))
    sales = cmp.metrics["sales_total"]
    assert (sales["current"], sales["previous"], sales["change"], sales["pct_change"]) == (1_500_000, 1_000_000, 500_000, "50.0")
    assert cmp.metrics["expenses_total"]["previous"] == 0
    assert cmp.metrics["expenses_total"]["pct_change"] is None
    assert cmp.length_warning is None


def test_compare_warns_when_lengths_differ(session):
    cmp = compare_periods(session, DateRange(D(2026, 10, 1), D(2026, 10, 15)), DateRange(D(2026, 9, 1), D(2026, 9, 30)))
    assert "مختلفتا الطول" in cmp.length_warning


def test_cashflow_insufficient_history_refuses_to_guess(session, txn):
    txn(D(2026, 10, 10), "sale", 100_000)
    cf = project_cashflow(session, D(2026, 10, 15))
    assert cf["is_estimate"] and cf["sufficient_data"] is False and cf["projected_net_change"] is None


def test_cashflow_known_numbers(session, txn):
    ref = D(2026, 10, 15)
    start = ref - timedelta(days=55)  # exactly the 56-day lookback
    # +100k cash sale on every one of 56 days, one 560k expense in the window
    for i in range(56):
        txn(start + timedelta(days=i), "sale", 100_000, desc=f"s{i}")
    txn(ref, "expense", 560_000)
    cf = project_cashflow(session, ref, horizon_days=30)
    total_net = 56 * 100_000 - 560_000                    # 5,040,000
    assert cf["sufficient_data"] is True
    assert cf["projected_net_change"] == total_net * 30 // 56   # 2,700,000 exactly
    assert cf["low"] <= cf["projected_net_change"] <= cf["high"]
    assert cf["is_estimate"] is True and "ضماناً" in cf["disclaimer_ar"]
    assert cf["avg_daily_cash_in"] == 100_000


def test_cashflow_ignores_credit_sales_as_cash(session, txn, parties):
    c1, _, _ = parties
    ref = D(2026, 10, 15)
    for i in range(56):
        txn(ref - timedelta(days=i), "sale", 100_000, "credit", customer_id=c1.id, desc=f"c{i}")
    cf = project_cashflow(session, ref)
    assert cf["projected_net_change"] == 0                   # nothing collected
    assert cf["outstanding_receivables"] == 5_600_000        # reported separately, not projected


@pytest.mark.parametrize("kwargs", [dict(horizon_days=0), dict(horizon_days=91), dict(lookback_days=10), dict(lookback_days=50)])
def test_cashflow_argument_validation(session, kwargs):
    with pytest.raises(ValueError):
        project_cashflow(session, D(2026, 10, 15), **kwargs)
