from datetime import date
from decimal import Decimal

import pytest

from app.services.money import InvalidAmount, format_iqd, parse_amount, round_half_up_div
from app.services.periods import DateRange, InvalidDateRange, named_period, parse_date, parse_range
from app.services.text import normalize_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        (1500, 1500),
        ("1,250,000", 1_250_000),
        ("١٢٥٠٠٠٠", 1_250_000),
        ("١٬٢٥٠٬٠٠٠", 1_250_000),
        ("1250000.00", 1_250_000),
        ("1 250 000 د.ع", 1_250_000),
        (Decimal("5000"), 5000),
    ],
)
def test_parse_amount_valid(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", [0, -5, "-100", "abc", "", "1500.5", "NaN", "Infinity", 10.5, 1500.0, True, None, 10**12, []])
def test_parse_amount_invalid(raw):
    with pytest.raises(InvalidAmount):
        parse_amount(raw)


def test_format_and_rounding():
    assert format_iqd(1250000) == "1,250,000 د.ع"
    assert round_half_up_div(5, 2) == 3
    assert round_half_up_div(-5, 2) == -3
    assert round_half_up_div(4, 3) == 1
    assert round_half_up_div(0, 7) == 0


def test_normalize_text_unifies_arabic_variants():
    assert normalize_text("  أحمد   إبراهيم ") == normalize_text("احمد ابراهيم")
    assert normalize_text("فاتورة ١٢٣") == "فاتورة 123"
    assert normalize_text(None) == ""


def test_daterange_inclusive_and_validation():
    r = DateRange(date(2026, 10, 1), date(2026, 10, 7))
    assert r.days == 7 and r.contains(date(2026, 10, 1)) and r.contains(date(2026, 10, 7))
    assert not r.contains(date(2026, 10, 8))
    assert r.previous() == DateRange(date(2026, 9, 24), date(2026, 9, 30))
    with pytest.raises(InvalidDateRange):
        DateRange(date(2026, 10, 8), date(2026, 10, 1))
    with pytest.raises(InvalidDateRange):
        DateRange(date(1900, 1, 1), date(2026, 1, 1))


def test_parse_date_and_range_errors():
    assert parse_date("2026-10-05") == date(2026, 10, 5)
    for bad in ("2026-13-01", "05/10/2026", "", None, 20261005):
        with pytest.raises(InvalidDateRange):
            parse_date(bad)
    assert parse_range("2026-10-01", "2026-10-02").days == 2


def test_named_periods_on_a_thursday():
    ref = date(2026, 10, 15)  # Thursday
    assert named_period("today", ref) == DateRange(ref, ref)
    assert named_period("yesterday", ref).start == date(2026, 10, 14)
    assert named_period("this_week", ref) == DateRange(date(2026, 10, 11), ref)  # week starts Sunday
    assert named_period("last_week", ref) == DateRange(date(2026, 10, 4), date(2026, 10, 10))
    assert named_period("this_month", ref) == DateRange(date(2026, 10, 1), ref)
    assert named_period("last_month", ref) == DateRange(date(2026, 9, 1), date(2026, 9, 30))
    assert named_period("last_month_same_span", ref) == DateRange(date(2026, 9, 1), date(2026, 9, 15))
    assert named_period("last_7_days", ref).days == 7
    assert named_period("last_30_days", ref).days == 30
    with pytest.raises(InvalidDateRange):
        named_period("next_decade", ref)


def test_month_edges():
    assert named_period("last_month", date(2026, 3, 31)) == DateRange(date(2026, 2, 1), date(2026, 2, 28))
    assert named_period("last_month_same_span", date(2026, 3, 31)).end == date(2026, 2, 28)  # clamped
    assert named_period("last_month", date(2026, 1, 10)) == DateRange(date(2025, 12, 1), date(2025, 12, 31))
    assert named_period("last_month", date(2024, 3, 1)).end == date(2024, 2, 29)  # leap year
