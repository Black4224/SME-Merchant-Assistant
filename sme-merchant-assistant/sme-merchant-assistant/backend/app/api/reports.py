from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Category
from app.services import reports
from app.services.cashflow import project_cashflow
from app.services.settings_service import get_reference_date

router = APIRouter(prefix="/api", tags=["reports"])


def _range(session, period, start, end, default="this_month"):
    return reports.resolve_range(session, period, start, end, default)


@router.get("/dashboard/summary")
def dashboard(period: str | None = None, start: date | None = None, end: date | None = None,
              session: Session = Depends(get_session)):
    rng, label = _range(session, period, start, end)
    return reports.dashboard_summary(session, rng, label)


@router.get("/reports/summary")
def summary(period: str | None = None, start: date | None = None, end: date | None = None,
            granularity: str = Query("weekly", pattern="^(daily|weekly|monthly)$"),
            session: Session = Depends(get_session)):
    rng, label = _range(session, period, start, end, default="last_30_days")
    return reports.reports_summary(session, rng, label, granularity)


@router.get("/reports/debts")
def debts(session: Session = Depends(get_session)):
    return reports.debts_report(session)


@router.get("/reports/anomalies")
def anomalies(period: str | None = None, start: date | None = None, end: date | None = None,
              session: Session = Depends(get_session)):
    rng = _range(session, period, start, end)[0] if (period or start) else None
    return reports.anomalies_report(session, rng)


@router.get("/reports/cashflow")
def cashflow(horizon_days: int = Query(30, ge=1, le=90), session: Session = Depends(get_session)):
    return project_cashflow(session, get_reference_date(session), horizon_days=horizon_days)


@router.get("/categories")
def categories(session: Session = Depends(get_session)):
    return {"items": [{"id": c.id, "name": c.name, "kind": c.kind.value}
                      for c in session.scalars(select(Category).order_by(Category.kind, Category.name))]}
