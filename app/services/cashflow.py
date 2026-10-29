"""30-day cash-flow projection. ALWAYS an estimate, never a guarantee.

Method (deliberately simple and explainable):
  1. Look at the last `lookback_days` (default 56 = 8 full weeks) ending at the reference date.
  2. Daily net cash = cash_in - cash_out (see metrics.py). Days without activity count as 0.
  3. Base projection = (net cash over the lookback) x horizon / lookback_days.
  4. Range: +/- one population standard deviation of the 7-day net totals, scaled by
     sqrt(horizon / 7). This is a rough volatility band, NOT a statistical confidence interval.
The projection is a change in cash over the horizon; the opening cash balance is unknown.
"""
import math
from datetime import date, timedelta
from statistics import pstdev

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.services.customers import total_outstanding
from app.services.metrics import active_filter, daily_series
from app.services.money import round_half_up_div
from app.services.periods import DateRange

MIN_HISTORY_DAYS = 28
DISCLAIMER_AR = "هذا تقدير مبني على نشاط الأسابيع الماضية وليس ضماناً لدخل مستقبلي."


def project_cashflow(
    session: Session, reference_date: date, horizon_days: int = 30, lookback_days: int = 56
) -> dict:
    if not 1 <= horizon_days <= 90:
        raise ValueError("horizon_days must be between 1 and 90")
    if lookback_days < 14 or lookback_days % 7:
        raise ValueError("lookback_days must be a multiple of 7 and at least 14")

    window = DateRange(reference_date - timedelta(days=lookback_days - 1), reference_date)
    first_txn = session.scalar(select(func.min(Transaction.txn_date)).where(active_filter()))
    history_days = (reference_date - first_txn).days + 1 if first_txn else 0
    sufficient = history_days >= MIN_HISTORY_DAYS

    series = daily_series(session, window)
    nets = [d["cash_in"] - d["cash_out"] for d in series]
    total_in = sum(d["cash_in"] for d in series)
    total_out = sum(d["cash_out"] for d in series)
    total_net = total_in - total_out

    result = {
        "is_estimate": True,
        "disclaimer_ar": DISCLAIMER_AR,
        "method": "average daily net cash over lookback x horizon",
        "reference_date": reference_date.isoformat(),
        "lookback": window.to_dict(),
        "horizon_days": horizon_days,
        "history_days_available": history_days,
        "sufficient_data": sufficient,
        "outstanding_receivables": total_outstanding(session, reference_date),
        "receivables_note_ar": "ديون الزبائن غير محسوبة كمتوقع تحصيله؛ هي مبلغ مستحق فقط.",
    }
    if not sufficient:
        result.update(
            projected_net_change=None, low=None, high=None, checkpoints=[],
            note_ar=f"البيانات غير كافية للتوقع (المتوفر {history_days} يوم والمطلوب {MIN_HISTORY_DAYS} يوم على الأقل).",
        )
        return result

    base = round_half_up_div(total_net * horizon_days, lookback_days)
    weekly = [sum(nets[i : i + 7]) for i in range(0, len(nets), 7)]
    band = int(round(pstdev(weekly) * math.sqrt(horizon_days / 7)))
    checkpoints = [
        {"day": d, "cumulative_net": round_half_up_div(total_net * d, lookback_days)}
        for d in (7, 14, 21, 30, horizon_days)
        if d <= horizon_days
    ]
    seen, unique = set(), []
    for c in checkpoints:
        if c["day"] not in seen:
            seen.add(c["day"])
            unique.append(c)
    result.update(
        avg_daily_cash_in=round_half_up_div(total_in, lookback_days),
        avg_daily_cash_out=round_half_up_div(total_out, lookback_days),
        projected_net_change=base,
        low=base - band,
        high=base + band,
        checkpoints=unique,
        note_ar=DISCLAIMER_AR,
    )
    return result
