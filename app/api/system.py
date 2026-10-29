from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, get_session
from app.errors import Unprocessable
from app.models import Transaction
from app.ai.rules_provider import RULES_MODE_NOTE_AR
from app.schemas.transactions import ResetDemoIn, SettingsUpdate
from app.services.settings_service import DEFAULTS, get_reference_date, get_setting, set_setting

router = APIRouter(prefix="/api", tags=["system"])
VERSION = "0.2.0"


def _settings_payload(session: Session) -> dict:
    cfg = get_settings()
    return {
        "business_name": get_setting(session, "business_name"),
        "currency_display": get_setting(session, "currency_display"),
        "credit_terms_days": int(get_setting(session, "credit_terms_days")),
        "is_demo_data": get_setting(session, "is_demo_data") == "true",
        "reference_date": get_reference_date(session).isoformat(),
        "transactions_count": session.scalar(select(func.count()).select_from(Transaction)) or 0,
        "ai": {"provider": cfg.ai_provider, "configured": cfg.ai_configured,
               "message_ar": RULES_MODE_NOTE_AR if cfg.ai_provider == "rules" else None if cfg.ai_configured else "مفتاح الذكاء الاصطناعي غير مضبوط؛ الحسابات المالية تعمل بشكل طبيعي لكن المساعد الذكي غير متاح."},
        "demo_notice_ar": "البيانات الحالية تجريبية (اصطناعية) لأغراض العرض فقط." if get_setting(session, "is_demo_data") == "true" else None,
    }


@router.get("/health")
def health(session: Session = Depends(get_session)):
    session.execute(text("SELECT 1"))
    cfg = get_settings()
    return {"status": "ok", "version": VERSION, "database": "ok", "ai_configured": cfg.ai_configured,
            "is_demo_data": get_setting(session, "is_demo_data") == "true"}


@router.get("/settings")
def read_settings(session: Session = Depends(get_session)):
    return _settings_payload(session)


@router.put("/settings")
def update_settings(body: SettingsUpdate, session: Session = Depends(get_session)):
    for key, value in body.model_dump(exclude_none=True).items():
        set_setting(session, key, str(value))
    session.commit()
    return _settings_payload(session)


@router.post("/settings/reset-demo")
def reset_demo(body: ResetDemoIn, session: Session = Depends(get_session)):
    """DESTRUCTIVE: wipes ALL data and reloads the synthetic demo dataset."""
    if body.confirm != "RESET":
        raise Unprocessable('للتأكيد أرسل confirm = "RESET"', code="confirmation_required")
    from scripts.seed_demo import seed_database

    bind = session.get_bind()
    session.close()
    Base.metadata.drop_all(bind)
    Base.metadata.create_all(bind)
    from sqlalchemy.orm import Session as S

    with S(bind, expire_on_commit=False) as fresh:
        n = seed_database(fresh)
    return {"reset": True, "transactions_loaded": n}
