"""Exact IQD money handling. Authoritative amounts are always `int` dinars.

Floats are rejected on purpose: binary floating point must never touch money.
"""
from decimal import Decimal, InvalidOperation

CURRENCY_SYMBOL = "د.ع"
MAX_AMOUNT_IQD = 100_000_000_000  # 100 billion - sanity ceiling for a small merchant

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SEPARATORS = {ord(c): None for c in ",٬ \u00a0\u202f_"}


class InvalidAmount(ValueError):
    """Raised when an amount cannot be represented as a positive whole IQD value."""


def parse_amount(value: object) -> int:
    """Parse user/CSV input into a positive whole number of dinars.

    Accepts int, or text such as "1,250,000", "١٢٥٠٠٠٠", "1250000.00", "1 250 000 د.ع".
    Rejects float, bool, zero, negatives, fractions (IQD fils are not tracked),
    NaN/inf and absurdly large values.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise InvalidAmount("المبلغ يجب أن يكون رقماً صحيحاً وليس عشرياً عائماً")
    if isinstance(value, int):
        amount = value
    elif isinstance(value, Decimal):
        amount = _decimal_to_int(value)
    elif isinstance(value, str):
        text = value.strip().translate(_ARABIC_DIGITS)
        text = text.replace(CURRENCY_SYMBOL, "").replace("IQD", "").replace("iqd", "")
        text = text.translate(_SEPARATORS).replace("٫", ".")
        if not text:
            raise InvalidAmount("المبلغ فارغ")
        try:
            amount = _decimal_to_int(Decimal(text))
        except InvalidOperation:
            raise InvalidAmount(f"المبلغ غير صالح: {value!r}") from None
    else:
        raise InvalidAmount(f"نوع المبلغ غير مدعوم: {type(value).__name__}")

    if amount <= 0:
        raise InvalidAmount("المبلغ يجب أن يكون أكبر من صفر")
    if amount > MAX_AMOUNT_IQD:
        raise InvalidAmount("المبلغ كبير بشكل غير منطقي")
    return amount


def _decimal_to_int(d: Decimal) -> int:
    if not d.is_finite():
        raise InvalidAmount("المبلغ غير صالح")
    if d != d.to_integral_value():
        raise InvalidAmount("المبلغ يجب أن يكون بالدينار الصحيح بدون كسور")
    return int(d)


def format_iqd(amount: int) -> str:
    """1250000 -> '1,250,000 د.ع' (negative amounts keep their sign)."""
    return f"{amount:,} {CURRENCY_SYMBOL}"


def round_half_up_div(numerator: int, denominator: int) -> int:
    """Exact integer division rounded half away from zero."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) * 2 + denominator) // (denominator * 2))
