"""Key/value application settings stored in the database."""
from datetime import date

from sqlalchemy.orm import Session

from app.models import AppSetting

DEFAULTS = {
    "business_name": "متجر تجريبي",
    "currency_display": "د.ع",
    "is_demo_data": "false",
    "reference_date": "",  # empty => use the real current date
    "credit_terms_days": "30",
}


def get_setting(session: Session, key: str) -> str:
    row = session.get(AppSetting, key)
    return row.value if row else DEFAULTS[key]


def set_setting(session: Session, key: str, value: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting: {key}")
    row = session.get(AppSetting, key)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))
    session.flush()


def get_reference_date(session: Session) -> date:
    """'Today' for all reports. Demo data pins this so results are reproducible."""
    raw = get_setting(session, "reference_date")
    return date.fromisoformat(raw) if raw else date.today()


def get_credit_terms_days(session: Session) -> int:
    return int(get_setting(session, "credit_terms_days"))
