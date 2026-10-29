"""Date ranges. Every range is INCLUSIVE on both ends: [start, end]."""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

MAX_RANGE_DAYS = 3660
SUNDAY = 6  # python weekday(): Monday=0 ... Sunday=6. Iraqi business week starts Sunday.


class InvalidDateRange(ValueError):
    pass


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or not isinstance(self.end, date):
            raise InvalidDateRange("start and end must be dates")
        if self.start > self.end:
            raise InvalidDateRange("تاريخ البداية بعد تاريخ النهاية")
        if self.days > MAX_RANGE_DAYS:
            raise InvalidDateRange("الفترة المطلوبة طويلة جداً")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def each_day(self):
        for i in range(self.days):
            yield self.start + timedelta(days=i)

    def previous(self) -> "DateRange":
        """The equally long range immediately before this one."""
        return DateRange(self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days}


def parse_date(value: object) -> date:
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise InvalidDateRange(f"تاريخ غير صالح: {value!r} (الصيغة المطلوبة YYYY-MM-DD)")


def parse_range(start: object, end: object) -> DateRange:
    return DateRange(parse_date(start), parse_date(end))


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _shift_month(d: date, months: int) -> tuple[int, int]:
    idx = d.year * 12 + (d.month - 1) + months
    return idx // 12, idx % 12 + 1


PERIOD_NAMES = (
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "last_month_same_span",
    "last_7_days",
    "last_30_days",
)


def named_period(name: str, ref: date, week_start: int = SUNDAY) -> DateRange:
    """Resolve a symbolic period relative to `ref` ("today").

    this_week / this_month are period-to-date (they end at `ref`).
    last_week / last_month are complete periods.
    last_month_same_span is the previous month cut to the same elapsed days as
    this_month, which is the fair comparison base for a month-to-date figure.
    """
    if name == "today":
        return DateRange(ref, ref)
    if name == "yesterday":
        y = ref - timedelta(days=1)
        return DateRange(y, y)
    if name in ("this_week", "last_week"):
        start = ref - timedelta(days=(ref.weekday() - week_start) % 7)
        if name == "this_week":
            return DateRange(start, ref)
        return DateRange(start - timedelta(days=7), start - timedelta(days=1))
    if name == "this_month":
        return DateRange(_month_start(ref), ref)
    if name in ("last_month", "last_month_same_span"):
        y, m = _shift_month(ref, -1)
        last_day = calendar.monthrange(y, m)[1]
        start = date(y, m, 1)
        if name == "last_month":
            return DateRange(start, date(y, m, last_day))
        return DateRange(start, date(y, m, min(ref.day, last_day)))
    if name == "last_7_days":
        return DateRange(ref - timedelta(days=6), ref)
    if name == "last_30_days":
        return DateRange(ref - timedelta(days=29), ref)
    raise InvalidDateRange(f"فترة غير معروفة: {name!r}")
