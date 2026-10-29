"""Compare two periods (e.g. this month vs last month)."""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.services.metrics import PeriodSummary, summarize_period
from app.services.periods import DateRange

COMPARED_METRICS = (
    "sales_total",
    "sales_credit",
    "customer_payments",
    "expenses_total",
    "purchases_total",
    "estimated_profit",
    "net_cash_flow",
)


def pct_change(current: int, previous: int) -> Decimal | None:
    """Percent change to 1 decimal place; None when the base is zero (undefined)."""
    if previous == 0:
        return None
    pct = Decimal(current - previous) * 100 / Decimal(abs(previous))
    return pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PeriodComparison:
    current: PeriodSummary
    previous: PeriodSummary
    metrics: dict[str, dict]
    length_warning: str | None

    def to_dict(self) -> dict:
        return {
            "current": self.current.to_dict(),
            "previous": self.previous.to_dict(),
            "metrics": self.metrics,
            "length_warning": self.length_warning,
        }


def compare_periods(
    session: Session, current: DateRange, previous: DateRange, *, include_ids: bool = False
) -> PeriodComparison:
    a = summarize_period(session, current, include_ids=include_ids)
    b = summarize_period(session, previous, include_ids=include_ids)
    metrics = {}
    for name in COMPARED_METRICS:
        cur, prev = getattr(a, name), getattr(b, name)
        pc = pct_change(cur, prev)
        metrics[name] = {
            "current": cur,
            "previous": prev,
            "change": cur - prev,
            "pct_change": str(pc) if pc is not None else None,
        }
    warning = None
    if current.days != previous.days:
        warning = f"الفترتان مختلفتا الطول ({current.days} يوم مقابل {previous.days} يوم) فالمقارنة تقريبية"
    return PeriodComparison(a, b, metrics, warning)
